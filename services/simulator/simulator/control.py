"""Sends a control command to the running simulator through Kafka.

Usage:
  python -m simulator.control offline_zone <h3_zone> [seconds]
  python -m simulator.control online_all
"""
import sys

from shared import events
from shared.kafka_io import make_producer


def main(argv):
    if not argv or argv[0] not in ("offline_zone", "online_all"):
        sys.exit(__doc__)
    cmd = {"action": argv[0]}
    if argv[0] == "offline_zone":
        cmd["zone"] = argv[1]
        cmd["seconds"] = float(argv[2]) if len(argv) > 2 else 120
    producer = make_producer()
    producer.send(events.TOPIC_SIM_CONTROL, key=None, value=cmd)
    producer.flush(timeout=10)
    print(f"sent {cmd}")


if __name__ == "__main__":
    main(sys.argv[1:])
