"""Measures Redis proximity lookups and end-to-end matching against a real
Redis and a real OSRM, using a separate Redis logical database so live demo
keys are not touched.

Environment: REDIS_HOST, REDIS_PORT (6379), REDIS_SSL (0/1), MEASURE_DB (1),
OSRM_URL, LABEL (free text describing where this ran).
"""
import os
import random
import statistics
import time
import uuid
from datetime import datetime, timezone

import redis

from matching.driver_index import DriverIndex
from matching.geo import zone_of
from matching.matcher import match_ride
from matching.osrm_client import OsrmClient
from shared.events import DEMO_AREA

DRIVERS = 20
GEOSEARCH_RUNS = 2000
MATCH_RUNS = 500


def pct(values, p):
    values = sorted(values)
    k = max(0, min(len(values) - 1, round(p / 100 * (len(values) - 1))))
    return values[k]


def summary(name, ms, what):
    print(f"{name}")
    print(f"  measures: {what}")
    print(f"  n={len(ms)} p50={pct(ms, 50):.3f} ms p95={pct(ms, 95):.3f} ms "
          f"p99={pct(ms, 99):.3f} ms max={max(ms):.3f} ms mean={statistics.mean(ms):.3f} ms")


def random_point(rng):
    south, west, north, east = DEMO_AREA
    return rng.uniform(south, north), rng.uniform(west, east)


def main():
    rng = random.Random(42)
    r = redis.Redis(host=os.environ.get("REDIS_HOST", "redis"), port=int(os.environ.get("REDIS_PORT", "6379")),
                    ssl=os.environ.get("REDIS_SSL", "0") == "1", db=int(os.environ.get("MEASURE_DB", "1")))
    r.flushdb()
    index = DriverIndex(r, zone_of)
    osrm = OsrmClient(os.environ.get("OSRM_URL", "http://osrm:5000"))

    def place_all():
        now = int(time.time() * 1000)
        index.apply_positions([{"driver_id": f"M{i:02d}", "lat": lat, "lng": lng, "status": "available", "ts": now}
                               for i, (lat, lng) in enumerate(random_point(rng) for _ in range(DRIVERS))])

    place_all()
    print(f"date_utc: {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}")
    print(f"environment: {os.environ.get('LABEL', 'unspecified')}")
    print(f"drivers indexed: {DRIVERS}, search radius 6000 m, Redis db {os.environ.get('MEASURE_DB', '1')}")

    raw, nearest = [], []
    for _ in range(GEOSEARCH_RUNS):
        lat, lng = random_point(rng)
        t = time.perf_counter()
        r.geosearch("drivers:available", longitude=lng, latitude=lat, radius=6000, unit="m",
                    sort="ASC", count=10, withdist=True)
        raw.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        index.nearest_available(lat, lng)
        nearest.append((time.perf_counter() - t) * 1000)

    lookup, total, statuses = [], [], {}
    for _ in range(MATCH_RUNS):
        p, d = random_point(rng), random_point(rng)
        ride = {"ride_id": uuid.uuid4().hex, "client_id": "C1", "requested_at": 0,
                "pickup": {"lat": p[0], "lng": p[1]}, "dropoff": {"lat": d[0], "lng": d[1]}}
        res = match_ride(index, osrm, ride)
        statuses[res["status"]] = statuses.get(res["status"], 0) + 1
        lookup.append(res["lookup_ms"])
        if res["status"] == "MATCHED":
            total.append(res["total_ms"])
        # Release every claim and re-place drivers so each run sees 20 drivers.
        for key in r.scan_iter(match="claim:*"):
            r.delete(key)
        place_all()

    print()
    summary("redis_geosearch_ms", raw, "one GEOSEARCH round trip from this client (radius 6 km, 10 results)")
    summary("nearest_available_ms", nearest,
            "GEOSEARCH plus one pipelined freshness and claim check (2 round trips)")
    summary("match_lookup_ms", lookup, "nearest_available plus the atomic SET NX claim of the chosen driver")
    summary("match_total_ms", total,
            "full match_ride: zone supply and demand reads, lookup, claim, 2 OSRM routes, pricing")
    print(f"match outcomes: {statuses}")
    r.flushdb()


if __name__ == "__main__":
    main()
