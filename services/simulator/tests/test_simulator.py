import pytest

from shared import events
from simulator.fleet import AVAILABLE, EN_ROUTE, IN_TRIP, OFFLINE, PICKUP_WAIT_S, Fleet
from simulator.route import RoutePath


class LineOsrm:
    """Straight two-point 'routes' at 10 m/s, enough to test the state flow."""

    def route(self, a, b, geometry=False):
        from simulator.route import _haversine_m
        d = _haversine_m(a, b)
        return {"distance_m": d, "duration_s": max(d / 10.0, 1.0), "coordinates": [a, b]}


def test_route_interpolates_at_constant_speed():
    path = RoutePath([(0.0, 0.0), (0.0, 0.01)], duration_s=111.0)  # about 1113 m
    assert path.speed_mps == pytest.approx(10.03, rel=0.01)
    lat, lng = path.advance(55.5)
    assert lng == pytest.approx(0.005, rel=0.01)
    path.advance(1000)
    assert path.done and path.position() == (0.0, 0.01)


def make_fleet(size=3):
    bus = events.RecordingBus()
    return Fleet(LineOsrm(), bus, size=size, seed=1, speed_factor=1.0, zone_of=lambda la, ln: "z"), bus


def test_fleet_publishes_one_position_per_driver():
    fleet, _ = make_fleet()
    out = fleet.tick(1.0, 0)
    assert [p["driver_id"] for p in out] == ["D01", "D02", "D03"]
    assert all(p["status"] == AVAILABLE for p in out)


def test_assignment_runs_full_lifecycle():
    fleet, bus = make_fleet(size=1)
    d = fleet.drivers[0]
    pickup = {"lat": d.position[0] + 0.001, "lng": d.position[1]}
    dropoff = {"lat": d.position[0] + 0.002, "lng": d.position[1]}
    fleet.assign({"ride_id": "r1", "client_id": "C1", "driver_id": "D01", "pickup": pickup,
                  "dropoff": dropoff, "price_kes": 300, "requested_at": 1}, 0)
    assert d.status == EN_ROUTE
    for _ in range(40):
        fleet.tick(1.0, 0)
    for _ in range(PICKUP_WAIT_S + 40):
        fleet.tick(1.0, 0)
    types = [t for t, _ in bus.events]
    assert types == [events.DRIVER_EN_ROUTE, events.DRIVER_ARRIVED, events.TRIP_STARTED,
                     events.TRIP_COMPLETED]
    completed = bus.events[-1][1]
    assert completed["price_kes"] == 300 and completed["dropoff"] == dropoff
    assert d.status == AVAILABLE and d.ride is None


def test_assignment_ignored_for_busy_driver():
    fleet, bus = make_fleet(size=1)
    fleet.drivers[0].status = IN_TRIP
    fleet.assign({"ride_id": "r1", "client_id": "C1", "driver_id": "D01",
                  "pickup": {"lat": 0, "lng": 0}, "dropoff": {"lat": 0, "lng": 0}}, 0)
    assert bus.events == []


def test_offline_zone_and_recovery():
    fleet, _ = make_fleet(size=2)
    fleet.control({"action": "offline_zone", "zone": "z", "seconds": 10}, now_s=100)
    assert all(d.status == OFFLINE for d in fleet.drivers)
    fleet.tick(1.0, now_s=105)
    assert all(d.status == OFFLINE for d in fleet.drivers)
    fleet.tick(1.0, now_s=111)
    assert all(d.status == AVAILABLE for d in fleet.drivers)
