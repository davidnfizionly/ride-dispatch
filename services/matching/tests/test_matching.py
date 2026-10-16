import fakeredis
import pytest

from matching import pricing
from matching.driver_index import DriverIndex, STALE_AFTER_MS
from matching.geo import zone_of
from matching.handlers import Deps, handle_positions, handle_ride_requested
from matching.matcher import match_ride
from shared import events

CBD = (-1.2864, 36.8172)
WESTLANDS = (-1.2676, 36.8108)


class Clock:
    def __init__(self, ms=1_000_000):
        self.ms = ms

    def __call__(self):
        return self.ms


class FakeOsrm:
    def route(self, a, b, geometry=False):
        return {"distance_m": 5000.0, "duration_s": 600.0}


class FakeProducer:
    def __init__(self):
        self.sent = []

    def send(self, topic, key=None, value=None):
        self.sent.append((topic, key, value))

    def flush(self, timeout=None):
        pass


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def index(clock):
    return DriverIndex(fakeredis.FakeRedis(), zone_of, clock_ms=clock)


def pos(driver_id, lat, lng, ts, status="available"):
    return {"driver_id": driver_id, "lat": lat, "lng": lng, "status": status, "ts": ts}


# pricing

def test_no_surge_when_zone_is_supplied():
    assert pricing.surge_multiplier(available=1, recent_requests=0) == 1.0


def test_surge_rises_as_supply_drops():
    values = [pricing.surge_multiplier(a, 2) for a in (3, 2, 1, 0)]
    assert values == [1.0, 1.25, 1.5, 1.75]


def test_surge_rises_with_demand_and_is_capped():
    assert pricing.surge_multiplier(1, 2) == 1.5
    assert pricing.surge_multiplier(0, 100) == pricing.MAX_SURGE


def test_fare_minimum_and_rounding():
    assert pricing.fare(100, 60, 1.0) == pricing.MIN_FARE
    # 100 + 40*10 + 4*20 = 580, x1.5 = 870
    assert pricing.fare(10_000, 1200, 1.5) == 870


# driver index

def test_nearest_returns_closest_first(index, clock):
    index.apply_positions([
        pos("far", *WESTLANDS, clock.ms),
        pos("near", CBD[0] + 0.001, CBD[1], clock.ms),
    ])
    found = index.nearest_available(*CBD)
    assert [d for d, _ in found] == ["near", "far"]
    assert found[0][1] < found[1][1]


def test_busy_and_stale_drivers_are_excluded(index, clock):
    index.apply_positions([
        pos("busy", *CBD, clock.ms, status="in_trip"),
        pos("old", *CBD, clock.ms - STALE_AFTER_MS - 1),
        pos("ok", *CBD, clock.ms),
    ])
    assert [d for d, _ in index.nearest_available(*CBD)] == ["ok"]


def test_out_of_order_message_is_ignored(index, clock):
    index.apply_positions([pos("d1", *CBD, clock.ms)])
    index.apply_positions([pos("d1", *WESTLANDS, clock.ms - 500, status="in_trip")])
    assert index.position("d1") == pytest.approx(CBD)
    assert index.nearest_available(*CBD)


def test_latest_message_in_batch_wins(index, clock):
    index.apply_positions([pos("d1", *WESTLANDS, clock.ms + 10), pos("d1", *CBD, clock.ms)])
    assert index.position("d1") == pytest.approx(WESTLANDS)


def test_claim_is_exclusive_and_survives_next_available_position(index, clock):
    index.apply_positions([pos("d1", *CBD, clock.ms)])
    assert index.claim("d1", "r1") is True
    assert index.claim("d1", "r2") is False
    # The simulator has not seen the assignment yet and still reports available.
    index.apply_positions([pos("d1", *CBD, clock.ms + 1000)])
    assert index.nearest_available(*CBD) == []
    assert index.zone_supply(zone_of(*CBD)) == 0


def test_zone_supply_follows_moves(index, clock):
    z_cbd, z_west = zone_of(*CBD), zone_of(*WESTLANDS)
    assert z_cbd != z_west
    index.apply_positions([pos("d1", *CBD, clock.ms)])
    assert index.zone_supply(z_cbd) == 1
    index.apply_positions([pos("d1", *WESTLANDS, clock.ms + 1)])
    assert (index.zone_supply(z_cbd), index.zone_supply(z_west)) == (0, 1)


def test_demand_window(index, clock):
    z = zone_of(*CBD)
    index.record_request(z, "r1")
    clock.ms += 11 * 60 * 1000
    index.record_request(z, "r2")
    assert index.recent_demand(z) == 1


# matcher

def ride(ride_id="r1", pickup=CBD, dropoff=WESTLANDS):
    return {
        "ride_id": ride_id, "client_id": "C1", "requested_at": 1,
        "pickup": {"lat": pickup[0], "lng": pickup[1]},
        "dropoff": {"lat": dropoff[0], "lng": dropoff[1]},
    }


def test_match_picks_nearest_and_prices(index, clock):
    index.apply_positions([
        pos("near", CBD[0] + 0.002, CBD[1], clock.ms),
        pos("near2", CBD[0] - 0.002, CBD[1] + 0.001, clock.ms),
        pos("far", *WESTLANDS, clock.ms),
    ])
    result = match_ride(index, FakeOsrm(), ride())
    assert result["status"] == "MATCHED"
    assert result["driver_id"] == "near"
    assert result["zone_available"] == 2
    assert result["surge"] == 1.0
    assert result["price_kes"] == pricing.fare(5000, 600, 1.0)
    assert result["lookup_ms"] >= 0


def test_two_rides_never_get_the_same_driver(index, clock):
    index.apply_positions([pos("only", *CBD, clock.ms)])
    first = match_ride(index, FakeOsrm(), ride("r1"))
    second = match_ride(index, FakeOsrm(), ride("r2"))
    assert first["status"] == "MATCHED"
    assert second["status"] == "NO_DRIVER"


def test_surge_applies_when_zone_is_short(index, clock):
    # The only driver is in a neighbouring zone, still within search radius.
    index.apply_positions([pos("d1", *WESTLANDS, clock.ms)])
    result = match_ride(index, FakeOsrm(), ride())
    assert result["status"] == "MATCHED"
    assert result["zone_available"] == 0
    assert result["surge"] == 1.25
    assert result["price_kes"] == pricing.fare(5000, 600, 1.25)


# handlers

def test_positions_handler_reads_msk_batch_and_emits_snapshot(index, clock):
    bus = events.RecordingBus()
    deps = Deps(index=index, osrm=FakeOsrm(), bus=bus, producer=FakeProducer())
    event = events.encode_msk_event([pos("d1", *CBD, clock.ms), pos("d2", *WESTLANDS, clock.ms)])
    assert handle_positions(event, deps) == {"received": 2, "applied": 2}
    detail_type, detail = bus.events[-1]
    assert detail_type == events.POSITIONS_SNAPSHOT
    assert [d["driver_id"] for d in detail["drivers"]] == ["d1", "d2"]
    cbd = next(z for z in detail["zones"] if z["zone"] == zone_of(*CBD))
    assert (cbd["available"], cbd["surge"]) == (1, 1.0)


def test_ride_requested_handler_assigns_and_emits(index, clock):
    index.apply_positions([pos("d1", *CBD, clock.ms)])
    bus, producer = events.RecordingBus(), FakeProducer()
    deps = Deps(index=index, osrm=FakeOsrm(), bus=bus, producer=producer)
    handle_ride_requested({"detail": ride()}, deps)
    assert [t for t, _ in bus.events] == [events.RIDE_SEARCHING, events.RIDE_MATCHED]
    topic, key, value = producer.sent[0]
    assert (topic, key, value["ride_id"]) == (events.TOPIC_ASSIGNMENTS, "d1", "r1")


def test_ride_requested_handler_no_driver(index):
    bus, producer = events.RecordingBus(), FakeProducer()
    deps = Deps(index=index, osrm=FakeOsrm(), bus=bus, producer=producer)
    handle_ride_requested({"detail": ride()}, deps)
    assert [t for t, _ in bus.events] == [events.RIDE_SEARCHING, events.RIDE_NO_DRIVER]
    assert producer.sent == []
