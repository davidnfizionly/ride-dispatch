"""SYNTHETIC ride history generator for the Athena demand query.

Every row is generated: seeded random pickups around a few Nairobi
neighbourhoods, an hourly demand curve, OSRM road distances and the project's
own pricing rules. Nothing here comes from a real ride-hailing service.

Output: <out>/synthetic_ride_history/dt=YYYY-MM-DD/part-000.json.gz (JSON lines),
same columns as the live rides table plus synthetic=true.

Usage: python -m simulator.history --out DIR [--days 7] [--end-date YYYY-MM-DD]
       [--seed 42] [--rides-per-day 600]
Environment: OSRM_URL
"""
import argparse
import gzip
import json
import os
import random
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from matching import pricing
from matching.geo import zone_of
from matching.osrm_client import OsrmClient

# name, lat, lng: neighbourhood centres used as pickup and dropoff anchors
PLACES = {
    "cbd": (-1.2864, 36.8172),
    "westlands": (-1.2676, 36.8108),
    "upper_hill": (-1.2995, 36.8143),
    "kilimani": (-1.2921, 36.7856),
    "lavington": (-1.2800, 36.7700),
    "ngara": (-1.2741, 36.8270),
    "south_b": (-1.3105, 36.8350),
}
RESIDENTIAL = ("kilimani", "lavington", "south_b", "ngara")

# Relative demand per hour of day (local time, UTC+3).
HOURLY = [2, 1, 1, 1, 2, 4, 8, 14, 16, 10, 7, 7, 8, 7, 6, 7, 10, 15, 17, 12, 9, 9, 7, 4]
EAT = timezone(timedelta(hours=3))


def pickup_weights(hour):
    w = {p: 1.0 for p in PLACES}
    if 6 <= hour <= 9:            # morning: leave home
        for p in RESIDENTIAL:
            w[p] = 3.0
    elif 16 <= hour <= 19:        # evening: leave work
        w["cbd"], w["upper_hill"], w["westlands"] = 4.0, 2.5, 2.5
    elif hour >= 20 or hour <= 1:  # night out
        w["westlands"] = 5.0
    return w


def pick(rng, weights):
    names = list(weights)
    return rng.choices(names, weights=[weights[n] for n in names])[0]


def jitter(rng, point, sd=0.006):
    return (point[0] + rng.gauss(0, sd), point[1] + rng.gauss(0, sd))


def generate(osrm, days, end, seed, rides_per_day):
    rng = random.Random(seed)
    total_weight = sum(HOURLY)
    rows = []
    for day_index in range(days):
        day = end - timedelta(days=days - 1 - day_index)
        weekend = day.weekday() >= 5
        for hour in range(24):
            expected = rides_per_day * HOURLY[hour] / total_weight * (0.8 if weekend else 1.0)
            n = max(0, round(rng.gauss(expected, expected ** 0.5)))
            peak = HOURLY[hour] / max(HOURLY)
            for _ in range(n):
                start = datetime(day.year, day.month, day.day, hour, tzinfo=EAT) + timedelta(
                    seconds=rng.uniform(0, 3600))
                origin = pick(rng, pickup_weights(hour))
                dest = pick(rng, {p: (0.2 if p == origin else 1.0) for p in PLACES})
                p, d = jitter(rng, PLACES[origin]), jitter(rng, PLACES[dest])
                route = osrm.route(p, d)
                available = max(0, round(rng.gauss(3.0 - 2.5 * peak, 0.8)))
                recent = max(0, round(rng.gauss(2.0 * peak, 0.7)))
                surge = pricing.surge_multiplier(available, recent)
                wait_s = rng.uniform(120, 600)
                done = start + timedelta(seconds=wait_s + route["duration_s"])
                rows.append({
                    "ride_id": str(uuid.UUID(int=rng.getrandbits(128))),
                    "client_id": f"SYN-C{rng.randint(1, 900):04d}",
                    "driver_id": f"SYN-D{rng.randint(1, 120):03d}",
                    "requested_at": start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    "completed_at": done.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    "pickup_lat": round(p[0], 6), "pickup_lng": round(p[1], 6),
                    "pickup_zone": zone_of(*p),
                    "dropoff_lat": round(d[0], 6), "dropoff_lng": round(d[1], 6),
                    "trip_distance_m": round(route["distance_m"]),
                    "trip_duration_s": round(route["duration_s"]),
                    "surge": surge,
                    "price_kes": pricing.fare(route["distance_m"], route["duration_s"], surge),
                    "synthetic": True,
                })
    return rows


def write(rows, out):
    by_day = {}
    for row in rows:
        by_day.setdefault(row["requested_at"][:10], []).append(row)
    for dt, items in sorted(by_day.items()):
        path = Path(out) / "synthetic_ride_history" / f"dt={dt}" / "part-000.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress("".join(json.dumps(r) + "\n" for r in items).encode()))
    return sorted(by_day)


def summary(rows):
    """Reference answer computed in Python, to cross-check the Athena query."""
    counts = Counter((r["pickup_zone"], r["requested_at"][:13]) for r in rows)
    (zone, hour), n = counts.most_common(1)[0]
    zone_totals = Counter(r["pickup_zone"] for r in rows)
    return {"rows": len(rows), "top_zone_hour": {"zone": zone, "hour_utc": hour, "rides": n},
            "top_zones_total": zone_totals.most_common(3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--end-date", default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--rides-per-day", type=int, default=600)
    a = ap.parse_args()
    end = date.fromisoformat(a.end_date) if a.end_date else datetime.now(timezone.utc).date() - timedelta(days=1)
    rows = generate(OsrmClient(os.environ.get("OSRM_URL", "http://osrm:5000")), a.days, end, a.seed,
                    a.rides_per_day)
    days = write(rows, a.out)
    print(json.dumps({"synthetic": True, "seed": a.seed, "days": a.days, "end_date": end.isoformat(),
                      "partitions": days, **summary(rows)}, indent=2))


if __name__ == "__main__":
    main()
