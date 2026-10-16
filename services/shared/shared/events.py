"""Event names, the event bus abstraction and MSK record decoding.

Copied into every Lambda package at build time (see scripts/build_lambdas.sh).
"""
import base64
import json
import time

SOURCE = "ride-dispatch"

# Ride lifecycle detail-types, in lifecycle order.
RIDE_REQUESTED = "RideRequested"
RIDE_SEARCHING = "RideSearching"
RIDE_MATCHED = "RideMatched"
RIDE_NO_DRIVER = "RideNoDriver"
DRIVER_EN_ROUTE = "DriverEnRoute"
DRIVER_ARRIVED = "DriverArrived"
TRIP_STARTED = "TripStarted"
TRIP_COMPLETED = "TripCompleted"

LIFECYCLE_EVENTS = (
    RIDE_REQUESTED, RIDE_SEARCHING, RIDE_MATCHED, RIDE_NO_DRIVER,
    DRIVER_EN_ROUTE, DRIVER_ARRIVED, TRIP_STARTED, TRIP_COMPLETED,
)

# Not a lifecycle step: periodic driver snapshot for the Live Ops Map.
POSITIONS_SNAPSHOT = "PositionsSnapshot"

# Kafka topics
TOPIC_POSITIONS = "driver-positions"
TOPIC_ASSIGNMENTS = "ride-assignments"
TOPIC_SIM_CONTROL = "sim-control"
# Used only by the local harness, which stands in for EventBridge.
TOPIC_LOCAL_EVENTS = "local-lifecycle-events"


# Area where rides may be requested: south, west, north, east.
SERVICE_AREA = (-1.45, 36.65, -1.16, 37.10)
# Central Nairobi, where simulated drivers wander while available.
DEMO_AREA = (-1.305, 36.780, -1.262, 36.835)


def in_service_area(lat, lng):
    south, west, north, east = SERVICE_AREA
    return south <= lat <= north and west <= lng <= east


def now_ms():
    return int(time.time() * 1000)


class EventBridgeBus:
    """Publishes to an EventBridge custom bus."""

    def __init__(self, client, bus_name):
        self._client = client
        self._bus_name = bus_name

    def put(self, detail_type, detail):
        resp = self._client.put_events(Entries=[{
            "Source": SOURCE,
            "DetailType": detail_type,
            "Detail": json.dumps(detail),
            "EventBusName": self._bus_name,
        }])
        if resp.get("FailedEntryCount"):
            raise RuntimeError(f"PutEvents failed: {resp['Entries']}")


class RecordingBus:
    """In-memory bus for tests and the local harness."""

    def __init__(self, on_put=None):
        self.events = []
        self._on_put = on_put

    def put(self, detail_type, detail):
        self.events.append((detail_type, detail))
        if self._on_put:
            self._on_put(detail_type, detail)


def decode_msk_event(event):
    """Returns the JSON values of an MSK event source mapping batch, in order.

    The event groups records by "topic-partition"; each value is base64.
    """
    out = []
    for records in event.get("records", {}).values():
        for record in records:
            raw = record.get("value")
            if raw:
                out.append(json.loads(base64.b64decode(raw)))
    return out


def encode_msk_event(values, topic=TOPIC_POSITIONS, partition=0):
    """Builds an MSK-shaped event from JSON values (tests and local harness)."""
    return {
        "eventSource": "aws:kafka",
        "records": {
            f"{topic}-{partition}": [
                {
                    "topic": topic,
                    "partition": partition,
                    "offset": i,
                    "value": base64.b64encode(json.dumps(v).encode()).decode(),
                }
                for i, v in enumerate(values)
            ]
        },
    }
