"""Prints the lag of both consumer groups on driver-positions at a fixed
interval: end offset minus committed offset, per group.

Runs inside the cluster (MSK is private). Environment: KAFKA_BOOTSTRAP,
KAFKA_IAM_REGION. Usage: python scripts/consumer_lag.py [seconds] [interval]
"""
import os
import sys
import time
from datetime import datetime, timezone

from kafka import KafkaConsumer, TopicPartition
from kafka.admin import KafkaAdminClient

from shared.events import TOPIC_POSITIONS
from shared.kafka_io import _MskIamTokenProvider

GROUPS = ("matching", "archiver")


def client_kwargs():
    kwargs = {"bootstrap_servers": os.environ["KAFKA_BOOTSTRAP"].split(",")}
    region = os.environ.get("KAFKA_IAM_REGION")
    if region:
        kwargs.update(security_protocol="SASL_SSL", sasl_mechanism="OAUTHBEARER",
                      sasl_oauth_token_provider=_MskIamTokenProvider(region))
    return kwargs


def main():
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 10
    admin = KafkaAdminClient(**client_kwargs())
    consumer = KafkaConsumer(**client_kwargs())
    partitions = [TopicPartition(TOPIC_POSITIONS, p) for p in sorted(consumer.partitions_for_topic(TOPIC_POSITIONS))]
    print(f"topic={TOPIC_POSITIONS} partitions={len(partitions)} groups={','.join(GROUPS)}")
    end = time.monotonic() + duration
    while True:
        ends = consumer.end_offsets(partitions)
        row = [f"{datetime.now(timezone.utc):%H:%M:%S}", f"end={sum(ends.values())}"]
        for group in GROUPS:
            committed = admin.list_consumer_group_offsets(group, partitions=partitions)
            lag = sum(ends[tp] - (committed[tp].offset if tp in committed and committed[tp].offset >= 0 else 0)
                      for tp in partitions)
            row.append(f"{group}_lag={lag}")
        print("  ".join(row), flush=True)
        if time.monotonic() >= end:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
