import gzip
import json

from archiver.handlers import Deps, handle_positions, handle_trip_completed
from shared import events


class MemStorage:
    def __init__(self):
        self.objects = {}

    def put(self, key, body):
        self.objects[key] = body


TS = 1_760_000_000_000  # 2025-10-09 08:53:20 UTC


def test_positions_batch_written_as_gzip_jsonl():
    storage = MemStorage()
    values = [{"driver_id": f"D{i}", "lat": -1.28, "lng": 36.82, "status": "available", "ts": TS + i}
              for i in range(3)]
    result = handle_positions(events.encode_msk_event(values), Deps(storage))
    assert result["archived"] == 3
    key, body = next(iter(storage.objects.items()))
    assert key.startswith("positions/dt=2025-10-09/hour=08/")
    lines = gzip.decompress(body).decode().splitlines()
    assert [json.loads(line)["driver_id"] for line in lines] == ["D0", "D1", "D2"]


def test_empty_batch_writes_nothing():
    storage = MemStorage()
    assert handle_positions(events.encode_msk_event([]), Deps(storage)) == {"archived": 0}
    assert storage.objects == {}


def test_trip_completed_written_as_flat_row():
    storage = MemStorage()
    detail = {
        "ride_id": "r1", "client_id": "C1", "driver_id": "D01", "requested_at": TS, "ts": TS + 600_000,
        "pickup": {"lat": -1.28, "lng": 36.82}, "dropoff": {"lat": -1.26, "lng": 36.81},
        "zone": "877a6e5a9ffffff", "surge": 1.25, "price_kes": 450,
        "trip_distance_m": 3377, "trip_duration_s": 239,
    }
    handle_trip_completed({"detail": detail}, Deps(storage))
    key, body = next(iter(storage.objects.items()))
    assert key == "rides/dt=2025-10-09/r1.json"
    row = json.loads(body)
    assert row["requested_at"] == "2025-10-09 08:53:20.000"
    assert row["completed_at"] == "2025-10-09 09:03:20.000"
    assert row["pickup_zone"] == "877a6e5a9ffffff" and row["price_kes"] == 450
