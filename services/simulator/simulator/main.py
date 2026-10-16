"""Simulator process: publishes driver positions to Kafka once per second,
reads ride assignments and control commands, and emits lifecycle events.

Environment:
  KAFKA_BOOTSTRAP, KAFKA_IAM_REGION (MSK only), OSRM_URL
  EVENT_SINK=eventbridge (EVENT_BUS_NAME) or kafka (local harness)
  FLEET_SIZE (20), SPEED_FACTOR (3), SEED (7), TICK_S (1)
"""
import json
import os
import queue
import threading
import time

from shared import events
from shared.kafka_io import make_consumer, make_producer

from matching.geo import zone_of
from matching.osrm_client import OsrmClient

from .fleet import Fleet


class KafkaSink:
    """Local stand-in for EventBridge: the harness reads this topic."""

    def __init__(self, producer):
        self._p = producer

    def put(self, detail_type, detail):
        self._p.send(events.TOPIC_LOCAL_EVENTS, key=detail.get("ride_id"),
                     value={"detail-type": detail_type, "detail": detail})


def _make_sink(producer):
    if os.environ.get("EVENT_SINK", "kafka") == "eventbridge":
        import boto3
        return events.EventBridgeBus(boto3.client("events"), os.environ["EVENT_BUS_NAME"])
    return KafkaSink(producer)


def _listen(commands):
    consumer = make_consumer([events.TOPIC_ASSIGNMENTS, events.TOPIC_SIM_CONTROL], "simulator")
    for msg in consumer:
        commands.put((msg.topic, msg.value))


def main():
    producer = make_producer()
    fleet = Fleet(
        OsrmClient(os.environ["OSRM_URL"], timeout_s=5),
        _make_sink(producer),
        size=int(os.environ.get("FLEET_SIZE", "20")),
        seed=int(os.environ.get("SEED", "7")),
        speed_factor=float(os.environ.get("SPEED_FACTOR", "3")),
        zone_of=zone_of,
    )
    commands = queue.Queue()
    threading.Thread(target=_listen, args=(commands,), daemon=True).start()

    tick_s = float(os.environ.get("TICK_S", "1"))
    sent = 0
    last_log = time.monotonic()
    print(json.dumps({"event": "started", "drivers": len(fleet.drivers)}), flush=True)
    while True:
        started = time.monotonic()
        while not commands.empty():
            topic, value = commands.get_nowait()
            if topic == events.TOPIC_ASSIGNMENTS:
                fleet.assign(value, time.time())
            else:
                fleet.control(value, time.time())
        for p in fleet.tick(tick_s, time.time()):
            producer.send(events.TOPIC_POSITIONS, key=p["driver_id"], value=p)
            sent += 1
        producer.flush()
        if started - last_log >= 30:
            print(json.dumps({"event": "rate", "positions_sent": sent,
                              "per_s": round(sent / (started - last_log), 1)}), flush=True)
            sent, last_log = 0, started
        time.sleep(max(0.0, tick_s - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
