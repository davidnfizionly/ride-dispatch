"""Surge scenario: take the drivers of one H3 zone offline and record how the
zone's supply, surge and quoted price change.

Steps: watch the zone, request ride A from the zone centre, send the
offline_zone command to the simulator through Kafka, watch again, request
ride B with the same pickup and dropoff, bring drivers back online.
Ride B's surge includes ride A as recent demand; the watch lines isolate the
supply effect.

Environment: WS_URL, WS_TOKEN, KAFKA_BOOTSTRAP (+ KAFKA_IAM_REGION on MSK).
Usage: python scripts/surge_demo.py [zone]
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

import h3
from websockets.asyncio.client import connect

from shared import events
from shared.kafka_io import make_producer

WATCH_S = 12
OFFLINE_S = 240


def stamp():
    return f"{datetime.now(timezone.utc):%H:%M:%S}"


async def next_snapshot(ws):
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("type") == events.POSITIONS_SNAPSHOT:
            return msg["detail"]


async def watch(ws, zone, seconds, label):
    end = time.monotonic() + seconds
    last = None
    while time.monotonic() < end:
        snap = await next_snapshot(ws)
        z = next(z for z in snap["zones"] if z["zone"] == zone)
        line = (z["available"], z["recent_requests"], z["surge"])
        if line != last:
            print(f"{stamp()}  {label:<7} zone={zone} available={z['available']} "
                  f"recent_requests={z['recent_requests']} surge={z['surge']}")
            last = line


async def request(ws, client_id, pickup, dropoff, label):
    await ws.send(json.dumps({"action": "requestRide", "client_id": client_id,
                              "pickup": pickup, "dropoff": dropoff}))
    ride_id = None
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("type") == "requestAck":
            ride_id = msg["ride_id"]
            continue
        d = msg.get("detail", {})
        if ride_id and d.get("ride_id") == ride_id and msg["type"] in (events.RIDE_MATCHED, events.RIDE_NO_DRIVER):
            print(f"{stamp()}  {label:<7} {msg['type']} driver={d.get('driver_id')} "
                  f"zone_available={d['zone_available']} recent_requests={d['zone_recent_requests']} "
                  f"surge={d['surge']} price_kes={d.get('price_kes')} trip_distance_m={d.get('trip_distance_m')}")
            return d


def control(producer, cmd):
    producer.send(events.TOPIC_SIM_CONTROL, key=None, value=cmd)
    producer.flush(timeout=10)
    print(f"{stamp()}  control {cmd}")


async def main():
    producer = make_producer()
    url = f"{os.environ['WS_URL']}?token={os.environ['WS_TOKEN']}"
    async with connect(url, max_size=2**20) as ws:
        print(f"date_utc: {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}")
        snap = await next_snapshot(ws)
        if len(sys.argv) > 1:
            zone = sys.argv[1]
        else:  # the best supplied zone gives the clearest before and after
            zone = max(snap["zones"], key=lambda z: z["available"])["zone"]
        lat, lng = h3.cell_to_latlng(zone)
        pickup = {"lat": round(lat, 6), "lng": round(lng, 6)}
        dropoff = {"lat": round(lat + 0.02, 6), "lng": round(lng + 0.01, 6)}
        print(f"zone: {zone} (H3 resolution {h3.get_resolution(zone)}), pickup at zone centre {pickup}")

        await watch(ws, zone, WATCH_S, "before")
        before = await request(ws, "C4", pickup, dropoff, "ride A")
        control(producer, {"action": "offline_zone", "zone": zone, "seconds": OFFLINE_S})
        # Request ride B as soon as the supply drop is visible, then keep
        # watching: drivers from nearby zones drift back in and surge eases.
        while True:
            snap = await next_snapshot(ws)
            z = next(z for z in snap["zones"] if z["zone"] == zone)
            if z["available"] == 0:
                print(f"{stamp()}  after   zone={zone} available=0 "
                      f"recent_requests={z['recent_requests']} surge={z['surge']}")
                break
        after = await request(ws, "C5", pickup, dropoff, "ride B")
        await watch(ws, zone, 2 * WATCH_S, "later")
        control(producer, {"action": "online_all"})
        print(f"result: surge {before['surge']} to {after['surge']}, "
              f"price_kes {before.get('price_kes')} to {after.get('price_kes')} for the same trip")


if __name__ == "__main__":
    asyncio.run(main())
