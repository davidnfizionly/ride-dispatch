"""Matches a ride request to the nearest available driver and prices it."""
import time

from . import pricing
from .geo import zone_of


def match_ride(index, osrm, ride, search_radius_m=6000, candidates=5):
    """Returns a result dict with status MATCHED or NO_DRIVER.

    lookup_ms covers the Redis nearest-driver search plus the atomic claim.
    total_ms also covers the two OSRM routes and pricing.
    """
    t0 = time.perf_counter()
    lat, lng = ride["pickup"]["lat"], ride["pickup"]["lng"]
    zone = zone_of(lat, lng)

    # Supply and demand are read before this ride claims a driver.
    available = index.zone_supply(zone)
    index.record_request(zone, ride["ride_id"])
    recent = index.recent_demand(zone) - 1  # requests other than this one
    surge = pricing.surge_multiplier(available, recent)

    t1 = time.perf_counter()
    driver_id = None
    for candidate, _dist in index.nearest_available(lat, lng, search_radius_m, candidates):
        if index.claim(candidate, ride["ride_id"]):
            driver_id = candidate
            break
    t2 = time.perf_counter()

    base = {
        "ride_id": ride["ride_id"],
        "client_id": ride.get("client_id"),
        "zone": zone,
        "zone_available": available,
        "zone_recent_requests": recent,
        "surge": surge,
        "lookup_ms": round((t2 - t1) * 1000, 3),
    }
    if driver_id is None:
        base["status"] = "NO_DRIVER"
        base["total_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return base

    pickup = (lat, lng)
    dropoff = (ride["dropoff"]["lat"], ride["dropoff"]["lng"])
    approach = osrm.route(index.position(driver_id), pickup)
    trip = osrm.route(pickup, dropoff)
    price = pricing.fare(trip["distance_m"], trip["duration_s"], surge)

    base.update({
        "status": "MATCHED",
        "driver_id": driver_id,
        "eta_s": round(approach["duration_s"]),
        "trip_distance_m": round(trip["distance_m"]),
        "trip_duration_s": round(trip["duration_s"]),
        "price_kes": price,
        "total_ms": round((time.perf_counter() - t0) * 1000, 3),
    })
    return base
