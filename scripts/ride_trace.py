"""Requests one ride over the WebSocket API and prints every lifecycle event
received for it, with the time elapsed since the request was sent.

Environment: WS_URL (without token), WS_TOKEN.
Usage: python scripts/ride_trace.py [client_id] [pickup_lat,lng] [dropoff_lat,lng]
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

from websockets.asyncio.client import connect

FINAL = {"TripCompleted", "RideNoDriver"}
SHOWN = ("driver_id", "driver_name", "eta_s", "sim_eta_s", "zone", "zone_available", "zone_recent_requests",
         "surge", "price_kes", "trip_distance_m", "lookup_ms", "total_ms")


def point(text, default):
    lat, lng = (float(x) for x in (text or default).split(","))
    return {"lat": lat, "lng": lng}


async def main():
    args = sys.argv[1:] + [None] * 3
    client_id = args[0] or "C1"
    pickup = point(args[1], "-1.2864,36.8172")     # CBD
    dropoff = point(args[2], "-1.2676,36.8108")    # Westlands
    url = f"{os.environ['WS_URL']}?token={os.environ['WS_TOKEN']}"

    async with connect(url, max_size=2**20) as ws:
        # The driver index starts empty: wait until positions are flowing.
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            if msg.get("type") == "PositionsSnapshot" and msg["detail"]["drivers"]:
                break
        print(f"date_utc: {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}")
        print(f"request: client={client_id} pickup={pickup} dropoff={dropoff}")
        t0 = time.perf_counter()
        await ws.send(json.dumps({"action": "requestRide", "client_id": client_id,
                                  "pickup": pickup, "dropoff": dropoff}))
        ride_id = None
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=900))
            if msg.get("type") == "requestAck":
                ride_id = msg.get("ride_id")
                print(f"{time.perf_counter() - t0:8.3f}s  ack status={msg['statusCode']} ride_id={ride_id}")
                continue
            detail = msg.get("detail", {})
            if not ride_id or detail.get("ride_id") != ride_id:
                continue
            shown = " ".join(f"{k}={detail[k]}" for k in SHOWN if k in detail)
            print(f"{time.perf_counter() - t0:8.3f}s  {msg['type']:<14} {shown}")
            if msg["type"] in FINAL:
                return


if __name__ == "__main__":
    asyncio.run(main())
