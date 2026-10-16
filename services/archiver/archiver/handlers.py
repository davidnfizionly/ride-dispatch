"""Lambda entry points for analytics archival.

positions_handler       MSK event source mapping, consumer group "archiver"
                        (same topic as matching, independent offsets)
trip_completed_handler  EventBridge rule on TripCompleted
"""
import gzip
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from shared import events


@dataclass
class Deps:
    storage: object


class S3Storage:
    def __init__(self, client, bucket):
        self._c, self._bucket = client, bucket

    def put(self, key, body):
        self._c.put_object(Bucket=self._bucket, Key=key, Body=body)


class LocalStorage:
    def __init__(self, root):
        self._root = Path(root)

    def put(self, key, body):
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def _utc(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _athena_ts(ms):
    return _utc(ms).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def ride_row(detail):
    """Flat row shared by the live rides table and the synthetic history table."""
    return {
        "ride_id": detail["ride_id"],
        "client_id": detail.get("client_id"),
        "driver_id": detail.get("driver_id"),
        "requested_at": _athena_ts(detail["requested_at"]),
        "completed_at": _athena_ts(detail["ts"]),
        "pickup_lat": detail["pickup"]["lat"],
        "pickup_lng": detail["pickup"]["lng"],
        "pickup_zone": detail.get("zone"),
        "dropoff_lat": detail["dropoff"]["lat"],
        "dropoff_lng": detail["dropoff"]["lng"],
        "trip_distance_m": detail.get("trip_distance_m"),
        "trip_duration_s": detail.get("trip_duration_s"),
        "surge": detail.get("surge"),
        "price_kes": detail.get("price_kes"),
    }


def handle_positions(event, deps):
    values = events.decode_msk_event(event)
    if not values:
        return {"archived": 0}
    first = _utc(min(v["ts"] for v in values))
    key = (f"positions/dt={first:%Y-%m-%d}/hour={first:%H}/"
           f"{first:%H%M%S}-{uuid.uuid4().hex[:8]}.json.gz")
    body = gzip.compress("\n".join(json.dumps(v) for v in values).encode() + b"\n")
    deps.storage.put(key, body)
    return {"archived": len(values), "key": key}


def handle_trip_completed(event, deps):
    row = ride_row(event["detail"])
    dt = row["completed_at"][:10]
    key = f"rides/dt={dt}/{row['ride_id']}.json"
    deps.storage.put(key, (json.dumps(row) + "\n").encode())
    return {"key": key}


_deps = None


def _aws_deps():
    global _deps
    if _deps is None:
        import boto3
        _deps = Deps(storage=S3Storage(boto3.client("s3"), os.environ["ARCHIVE_BUCKET"]))
    return _deps


def positions_handler(event, context):
    return handle_positions(event, _aws_deps())


def trip_completed_handler(event, context):
    return handle_trip_completed(event, _aws_deps())
