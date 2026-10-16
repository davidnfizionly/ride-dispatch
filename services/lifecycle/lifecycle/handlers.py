"""Lambda entry points for the ride lifecycle and the WebSocket API.

ws_connect_handler     $connect route, checks the deploy-time token
ws_disconnect_handler  $disconnect route
ws_request_handler     requestRide route, creates the ride and emits RideRequested
lifecycle_handler      EventBridge rule on lifecycle events, updates DynamoDB
notify_handler         EventBridge rule on lifecycle events and PositionsSnapshot,
                       pushes each event to every open WebSocket connection
"""
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass

from shared import events

from . import state_machine as sm

CLIENT_IDS = ("C1", "C2", "C3", "C4", "C5")
CONNECTION_TTL_S = 4 * 3600

# Copied onto the ride item when the matching state is reached.
MATCH_ATTRS = ("driver_id", "eta_s", "price_kes", "surge", "zone",
               "trip_distance_m", "trip_duration_s")


@dataclass
class Deps:
    rides: object
    connections: object
    bus: object
    post: object = None  # callable(connection_id, payload_bytes); raises GoneConnection
    connect_token: str = ""


class GoneConnection(Exception):
    pass


def _response(code, body=None):
    return {"statusCode": code, "body": json.dumps(body or {})}


def handle_connect(event, deps):
    token = (event.get("queryStringParameters") or {}).get("token", "")
    if not deps.connect_token or not hmac.compare_digest(token, deps.connect_token):
        return _response(401, {"error": "unauthorized"})
    deps.connections.add(event["requestContext"]["connectionId"], int(time.time()) + CONNECTION_TTL_S)
    return _response(200)


def handle_disconnect(event, deps):
    deps.connections.remove(event["requestContext"]["connectionId"])
    return _response(200)


def _valid_point(p):
    try:
        lat, lng = float(p["lat"]), float(p["lng"])
    except (KeyError, TypeError, ValueError):
        return None
    if not events.in_service_area(lat, lng):
        return None
    return {"lat": lat, "lng": lng}


def _ack(code, body):
    # Returned to the caller through the route response, shaped like a push message.
    return _response(code, {"type": "requestAck", "statusCode": code, **body})


def handle_request(event, deps):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _ack(400, {"error": "invalid json"})
    client_id = body.get("client_id")
    pickup, dropoff = _valid_point(body.get("pickup") or {}), _valid_point(body.get("dropoff") or {})
    if client_id not in CLIENT_IDS or not pickup or not dropoff:
        return _ack(400, {"client_id": client_id,
                          "error": "client_id, pickup and dropoff inside the service area are required"})

    ride = {
        "ride_id": str(uuid.uuid4()),
        "client_id": client_id,
        "pickup": pickup,
        "dropoff": dropoff,
        "requested_at": events.now_ms(),
    }
    deps.rides.create(ride)
    deps.bus.put(events.RIDE_REQUESTED, ride)
    return _ack(200, {"ride_id": ride["ride_id"], "client_id": client_id})


def handle_lifecycle(event, deps):
    detail_type, detail = event["detail-type"], event["detail"]
    target = sm.STATE_FOR_EVENT.get(detail_type)
    if target is None or target == sm.REQUESTED:
        return {"applied": False, "reason": "not a transition"}
    attrs = {k: detail[k] for k in MATCH_ATTRS if target == sm.MATCHED and k in detail}
    try:
        deps.rides.transition(detail["ride_id"], target, detail.get("ts", events.now_ms()), attrs)
    except sm.InvalidTransition as e:
        print(json.dumps({"metric": "transition_rejected", "detail_type": detail_type, "reason": str(e)}))
        return {"applied": False, "reason": str(e)}
    print(json.dumps({"metric": "transition", "ride_id": detail["ride_id"], "state": target}))
    return {"applied": True, "state": target}


def handle_notify(event, deps):
    payload = json.dumps({"type": event["detail-type"], "detail": event["detail"]}).encode()
    sent = gone = 0
    for connection_id in deps.connections.all():
        try:
            deps.post(connection_id, payload)
            sent += 1
        except GoneConnection:
            deps.connections.remove(connection_id)
            gone += 1
    return {"sent": sent, "gone": gone}


_deps = None


def _aws_deps():
    global _deps
    if _deps is None:
        import boto3

        from .stores import DynamoConnectionStore, DynamoRideStore

        ddb = boto3.resource("dynamodb")
        post = None
        if os.environ.get("WS_CALLBACK_URL"):
            api = boto3.client("apigatewaymanagementapi", endpoint_url=os.environ["WS_CALLBACK_URL"])

            def post(connection_id, data):
                try:
                    api.post_to_connection(ConnectionId=connection_id, Data=data)
                except api.exceptions.GoneException as e:
                    raise GoneConnection(connection_id) from e

        _deps = Deps(
            rides=DynamoRideStore(ddb.Table(os.environ["RIDES_TABLE"])),
            connections=DynamoConnectionStore(ddb.Table(os.environ["CONNECTIONS_TABLE"])),
            bus=events.EventBridgeBus(boto3.client("events"), os.environ["EVENT_BUS_NAME"]),
            post=post,
            connect_token=os.environ.get("CONNECT_TOKEN", ""),
        )
    return _deps


def ws_connect_handler(event, context):
    return handle_connect(event, _aws_deps())


def ws_disconnect_handler(event, context):
    return handle_disconnect(event, _aws_deps())


def ws_request_handler(event, context):
    return handle_request(event, _aws_deps())


def lifecycle_handler(event, context):
    return handle_lifecycle(event, _aws_deps())


def notify_handler(event, context):
    return handle_notify(event, _aws_deps())
