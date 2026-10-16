"""Ride and WebSocket connection storage: DynamoDB in AWS, in-memory locally."""
import threading
from decimal import Decimal

from . import state_machine as sm


def _to_dynamo(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(v) for v in value]
    return value


class DynamoRideStore:
    """Table key: ride_id. The status condition makes every transition atomic."""

    def __init__(self, table):
        self._t = table

    def create(self, ride):
        from botocore.exceptions import ClientError
        item = {**ride, "status": sm.REQUESTED, "history": {sm.REQUESTED: ride["requested_at"]}}
        try:
            self._t.put_item(Item=_to_dynamo(item), ConditionExpression="attribute_not_exists(ride_id)")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise sm.InvalidTransition(f"ride {ride['ride_id']} exists") from e
            raise

    def transition(self, ride_id, target, ts, attrs=None):
        from botocore.exceptions import ClientError
        prev = sm.allowed_previous(target)
        names = {"#s": "status", "#h": "history", "#t": target}
        values = {":t": target, ":ts": ts}
        sets = ["#s = :t", "#h.#t = :ts"]
        for i, (k, v) in enumerate((attrs or {}).items()):
            names[f"#a{i}"] = k
            values[f":a{i}"] = v
            sets.append(f"#a{i} = :a{i}")
        placeholders = []
        for i, state in enumerate(prev):
            values[f":p{i}"] = state
            placeholders.append(f":p{i}")
        try:
            self._t.update_item(
                Key={"ride_id": ride_id},
                UpdateExpression="SET " + ", ".join(sets),
                ConditionExpression=f"#s IN ({', '.join(placeholders)})",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=_to_dynamo(values),
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise sm.InvalidTransition(f"{ride_id} to {target}") from e
            raise

    def get(self, ride_id):
        return self._t.get_item(Key={"ride_id": ride_id}).get("Item")


class MemoryRideStore:
    def __init__(self):
        self._rides = {}
        self._lock = threading.Lock()

    def create(self, ride):
        with self._lock:
            if ride["ride_id"] in self._rides:
                raise sm.InvalidTransition(f"ride {ride['ride_id']} exists")
            self._rides[ride["ride_id"]] = {
                **ride, "status": sm.REQUESTED, "history": {sm.REQUESTED: ride["requested_at"]},
            }

    def transition(self, ride_id, target, ts, attrs=None):
        with self._lock:
            ride = self._rides.get(ride_id)
            if ride is None:
                raise sm.InvalidTransition(f"unknown ride {ride_id}")
            sm.check(ride["status"], target)
            ride["status"] = target
            ride["history"][target] = ts
            ride.update(attrs or {})

    def get(self, ride_id):
        with self._lock:
            ride = self._rides.get(ride_id)
            return None if ride is None else {**ride, "history": dict(ride["history"])}


class DynamoConnectionStore:
    """Table key: connection_id. A handful of connections at most (demo UI)."""

    def __init__(self, table):
        self._t = table

    def add(self, connection_id, ttl_epoch_s):
        self._t.put_item(Item={"connection_id": connection_id, "expires_at": ttl_epoch_s})

    def remove(self, connection_id):
        self._t.delete_item(Key={"connection_id": connection_id})

    def all(self):
        items, kwargs = [], {"ProjectionExpression": "connection_id"}
        while True:
            page = self._t.scan(**kwargs)
            items += [i["connection_id"] for i in page.get("Items", [])]
            if "LastEvaluatedKey" not in page:
                return items
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


class MemoryConnectionStore:
    def __init__(self):
        self._ids = set()
        self._lock = threading.Lock()

    def add(self, connection_id, ttl_epoch_s):
        with self._lock:
            self._ids.add(connection_id)

    def remove(self, connection_id):
        with self._lock:
            self._ids.discard(connection_id)

    def all(self):
        with self._lock:
            return list(self._ids)
