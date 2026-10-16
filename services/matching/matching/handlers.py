"""Lambda entry points for matching and pricing.

positions_handler      MSK event source mapping, consumer group "matching"
ride_requested_handler EventBridge rule on RideRequested
"""
import json
import os
from dataclasses import dataclass

from shared import events

from . import pricing
from .driver_index import DriverIndex
from .geo import demo_zones, zone_of
from .matcher import match_ride
from .osrm_client import OsrmClient

DEMO_ZONES = demo_zones()


@dataclass
class Deps:
    index: DriverIndex
    osrm: OsrmClient
    bus: object
    producer: object


def zone_stats(index, zones):
    """Current supply, demand and surge for each zone (Live Ops Map overlay)."""
    out = []
    for zone in zones:
        available, recent = index.zone_supply(zone), index.recent_demand(zone)
        out.append({"zone": zone, "available": available, "recent_requests": recent,
                    "surge": pricing.surge_multiplier(available, recent)})
    return out


def handle_positions(event, deps):
    positions = events.decode_msk_event(event)
    applied = deps.index.apply_positions(positions)
    deps.bus.put(events.POSITIONS_SNAPSHOT, {
        "ts": events.now_ms(),
        "drivers": deps.index.snapshot(),
        "zones": zone_stats(deps.index, DEMO_ZONES),
    })
    return {"received": len(positions), "applied": applied}


def handle_ride_requested(event, deps):
    ride = event["detail"]
    deps.bus.put(events.RIDE_SEARCHING, {
        "ride_id": ride["ride_id"], "client_id": ride["client_id"], "ts": events.now_ms(),
    })
    result = match_ride(deps.index, deps.osrm, ride)
    print(json.dumps({"metric": "match", **result}))

    detail = {
        **result,
        "pickup": ride["pickup"],
        "dropoff": ride["dropoff"],
        "requested_at": ride["requested_at"],
        "ts": events.now_ms(),
    }
    if result["status"] != "MATCHED":
        deps.bus.put(events.RIDE_NO_DRIVER, detail)
        return result

    # The simulator moves the driver once it reads the assignment.
    deps.producer.send(events.TOPIC_ASSIGNMENTS, key=result["driver_id"], value=detail)
    deps.producer.flush(timeout=5)
    deps.bus.put(events.RIDE_MATCHED, detail)
    return result


_deps = None


def _aws_deps():
    global _deps
    if _deps is None:
        import boto3
        import redis

        from shared.kafka_io import make_producer

        r = redis.Redis(
            host=os.environ["REDIS_HOST"], port=int(os.environ.get("REDIS_PORT", "6379")),
            ssl=True, socket_timeout=2,
        )
        _deps = Deps(
            index=DriverIndex(r, zone_of),
            osrm=OsrmClient(os.environ["OSRM_URL"]),
            bus=events.EventBridgeBus(boto3.client("events"), os.environ["EVENT_BUS_NAME"]),
            producer=make_producer(),
        )
    return _deps


def positions_handler(event, context):
    return handle_positions(event, _aws_deps())


def ride_requested_handler(event, context):
    return handle_ride_requested(event, _aws_deps())
