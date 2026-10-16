"""Simulated drivers moving on real Nairobi roads.

Each driver follows OSRM routes: random destinations while available, then to
the pickup and the dropoff once assigned. Time can be compressed with
speed_factor so a demo ride completes in a few minutes.
"""
import random

from shared import events

from .route import RoutePath

AVAILABLE, EN_ROUTE, IN_TRIP, OFFLINE = "available", "en_route", "in_trip", "offline"

DEMO_AREA = events.DEMO_AREA
PICKUP_WAIT_S = 5


class Driver:
    def __init__(self, driver_id, name):
        self.driver_id = driver_id
        self.name = name
        self.status = AVAILABLE
        self.path = None
        self.ride = None
        self.wait_s = 0.0
        self.offline_until = 0.0
        self.position = None


class Fleet:
    def __init__(self, osrm, sink, size=20, seed=7, speed_factor=3.0, zone_of=None):
        from faker import Faker

        self._osrm = osrm
        self._sink = sink
        self._rng = random.Random(seed)
        self._speed = speed_factor
        self._zone_of = zone_of
        fake = Faker()
        fake.seed_instance(seed)
        self.drivers = [Driver(f"D{i:02d}", fake.first_name()) for i in range(1, size + 1)]
        for d in self.drivers:
            start = self._random_point()
            self._wander(d, start)
            d.position = d.path.position()

    def _random_point(self):
        south, west, north, east = DEMO_AREA
        return (self._rng.uniform(south, north), self._rng.uniform(west, east))

    def _route(self, start, end):
        r = self._osrm.route(start, end, geometry=True)
        return RoutePath(r["coordinates"], r["duration_s"])

    def _wander(self, d, start=None):
        d.path = self._route(start or d.position, self._random_point())

    # Commands from Kafka

    def assign(self, a, now_s):
        d = self._by_id(a["driver_id"])
        if d is None or d.status != AVAILABLE:
            print(f"ignored assignment {a['ride_id']} for {a['driver_id']}: status "
                  f"{d.status if d else 'unknown'}")
            return
        pickup = (a["pickup"]["lat"], a["pickup"]["lng"])
        d.ride = a
        d.status = EN_ROUTE
        d.path = self._route(d.position, pickup)
        # Wall-clock ETA under time compression; RideMatched carries the real road ETA.
        self._emit(events.DRIVER_EN_ROUTE, d, sim_eta_s=round(d.path.remaining_s / self._speed))

    def control(self, cmd, now_s):
        if cmd.get("action") == "offline_zone" and self._zone_of:
            n = 0
            for d in self.drivers:
                if d.status == AVAILABLE and self._zone_of(*d.position) == cmd["zone"]:
                    d.status = OFFLINE
                    d.offline_until = now_s + float(cmd.get("seconds", 120))
                    n += 1
            print(f"offline_zone {cmd['zone']}: {n} drivers offline")
        elif cmd.get("action") == "online_all":
            for d in self.drivers:
                if d.status == OFFLINE:
                    d.offline_until = 0.0

    # Simulation step

    def tick(self, dt_s, now_s):
        """Moves every driver by dt_s of real time. Returns position messages."""
        sim_dt = dt_s * self._speed
        out = []
        for d in self.drivers:
            if d.status == OFFLINE:
                if now_s >= d.offline_until:
                    d.status = AVAILABLE
                    self._wander(d)
            elif d.wait_s > 0:
                d.wait_s -= sim_dt
                if d.wait_s <= 0:
                    self._start_trip(d)
            else:
                d.position = d.path.advance(sim_dt)
                if d.path.done:
                    self._arrived(d)
            out.append({
                "driver_id": d.driver_id,
                "lat": round(d.position[0], 6),
                "lng": round(d.position[1], 6),
                "status": d.status,
                "ride_id": d.ride["ride_id"] if d.ride else None,
                "ts": events.now_ms(),
            })
        return out

    def _arrived(self, d):
        if d.status == EN_ROUTE:
            self._emit(events.DRIVER_ARRIVED, d)
            d.wait_s = PICKUP_WAIT_S
        elif d.status == IN_TRIP:
            self._emit(events.TRIP_COMPLETED, d)
            d.ride = None
            d.status = AVAILABLE
            self._wander(d)
        else:
            self._wander(d)

    def _start_trip(self, d):
        dropoff = (d.ride["dropoff"]["lat"], d.ride["dropoff"]["lng"])
        d.status = IN_TRIP
        d.path = self._route(d.position, dropoff)
        self._emit(events.TRIP_STARTED, d)

    def _emit(self, detail_type, d, **extra):
        a = d.ride
        detail = {
            "ride_id": a["ride_id"], "client_id": a["client_id"], "driver_id": d.driver_id,
            "driver_name": d.name, "lat": d.position[0], "lng": d.position[1],
            "ts": events.now_ms(), **extra,
        }
        if detail_type == events.TRIP_COMPLETED:
            for k in ("pickup", "dropoff", "zone", "surge", "price_kes", "requested_at",
                      "trip_distance_m", "trip_duration_s"):
                detail[k] = a.get(k)
        self._sink.put(detail_type, detail)

    def _by_id(self, driver_id):
        return next((d for d in self.drivers if d.driver_id == driver_id), None)
