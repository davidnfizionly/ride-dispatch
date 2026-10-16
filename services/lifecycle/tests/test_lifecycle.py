import json

import pytest

from lifecycle import state_machine as sm
from lifecycle.handlers import (
    Deps, GoneConnection, handle_connect, handle_disconnect, handle_lifecycle,
    handle_notify, handle_request,
)
from lifecycle.stores import MemoryConnectionStore, MemoryRideStore
from shared import events

TOKEN = "s3cret-token"


@pytest.fixture
def deps():
    return Deps(
        rides=MemoryRideStore(), connections=MemoryConnectionStore(),
        bus=events.RecordingBus(), post=None, connect_token=TOKEN,
    )


def ws(connection_id="c1", token=None, body=None):
    e = {"requestContext": {"connectionId": connection_id}}
    if token is not None:
        e["queryStringParameters"] = {"token": token}
    if body is not None:
        e["body"] = json.dumps(body)
    return e


VALID = {"client_id": "C1", "pickup": {"lat": -1.2864, "lng": 36.8172},
         "dropoff": {"lat": -1.2676, "lng": 36.8108}}


# state machine

def test_main_path_is_accepted_in_order():
    for prev, nxt in zip(sm.MAIN_PATH, sm.MAIN_PATH[1:]):
        sm.check(prev, nxt)


def test_forward_skip_is_accepted_backward_is_rejected():
    sm.check(sm.REQUESTED, sm.MATCHED)
    with pytest.raises(sm.InvalidTransition):
        sm.check(sm.MATCHED, sm.SEARCHING)


def test_terminal_states_are_final():
    with pytest.raises(sm.InvalidTransition):
        sm.check(sm.COMPLETED, sm.IN_TRIP)
    with pytest.raises(sm.InvalidTransition):
        sm.check(sm.NO_DRIVER, sm.MATCHED)
    with pytest.raises(sm.InvalidTransition):
        sm.check(sm.MATCHED, sm.NO_DRIVER)


# websocket handlers

def test_connect_requires_token(deps):
    assert handle_connect(ws(token="wrong"), deps)["statusCode"] == 401
    assert handle_connect(ws(), deps)["statusCode"] == 401
    assert handle_connect(ws(token=TOKEN), deps)["statusCode"] == 200
    assert deps.connections.all() == ["c1"]
    handle_disconnect(ws(), deps)
    assert deps.connections.all() == []


def test_connect_rejected_when_no_token_configured(deps):
    deps.connect_token = ""
    assert handle_connect(ws(token=""), deps)["statusCode"] == 401


def test_request_creates_ride_and_emits(deps):
    resp = handle_request(ws(body=VALID), deps)
    assert resp["statusCode"] == 200
    ride_id = json.loads(resp["body"])["ride_id"]
    assert deps.rides.get(ride_id)["status"] == sm.REQUESTED
    assert deps.bus.events[0][0] == events.RIDE_REQUESTED


@pytest.mark.parametrize("body", [
    {**VALID, "client_id": "C9"},
    {**VALID, "pickup": {"lat": 51.5, "lng": -0.12}},
    {**VALID, "dropoff": {"lat": "x", "lng": 1}},
    {"client_id": "C1"},
])
def test_request_validation(deps, body):
    assert handle_request(ws(body=body), deps)["statusCode"] == 400
    assert deps.bus.events == []


# lifecycle

def _ride(deps):
    return json.loads(handle_request(ws(body=VALID), deps)["body"])["ride_id"]


def ev(detail_type, ride_id, **detail):
    return {"detail-type": detail_type, "detail": {"ride_id": ride_id, "ts": 5, **detail}}


def test_full_lifecycle_and_match_attributes(deps):
    rid = _ride(deps)
    for dt in (events.RIDE_SEARCHING, events.RIDE_MATCHED, events.DRIVER_EN_ROUTE,
               events.DRIVER_ARRIVED, events.TRIP_STARTED, events.TRIP_COMPLETED):
        extra = {"driver_id": "D01", "eta_s": 120, "price_kes": 450} if dt == events.RIDE_MATCHED else {}
        assert handle_lifecycle(ev(dt, rid, **extra), deps)["applied"] is True
    ride = deps.rides.get(rid)
    assert ride["status"] == sm.COMPLETED
    assert ride["driver_id"] == "D01" and ride["price_kes"] == 450
    assert set(ride["history"]) == set(sm.MAIN_PATH)


def test_late_event_is_ignored_not_applied(deps):
    rid = _ride(deps)
    handle_lifecycle(ev(events.RIDE_MATCHED, rid), deps)
    result = handle_lifecycle(ev(events.RIDE_SEARCHING, rid), deps)
    assert result["applied"] is False
    assert deps.rides.get(rid)["status"] == sm.MATCHED


def test_notify_broadcasts_and_drops_gone_connections(deps):
    deps.connections.add("alive", 0)
    deps.connections.add("gone", 0)
    sent = []

    def post(cid, data):
        if cid == "gone":
            raise GoneConnection(cid)
        sent.append((cid, json.loads(data)))

    deps.post = post
    result = handle_notify(ev(events.RIDE_MATCHED, "r1"), deps)
    assert result == {"sent": 1, "gone": 1}
    assert sent[0][1]["type"] == events.RIDE_MATCHED
    assert deps.connections.all() == ["alive"]
