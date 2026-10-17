"""Creates the Kafka topics (MSK has auto-creation disabled). Idempotent.

Usage: python -m simulator.topics
"""
import os

from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

from shared import events
from shared.kafka_io import _MskIamTokenProvider

# One partition for positions: each consumer group then runs at most one
# concurrent Lambda invocation, which keeps the whole design inside the
# account's concurrency limit (see docs/DECISIONS.md).
TOPICS = {
    events.TOPIC_POSITIONS: 1,
    events.TOPIC_ASSIGNMENTS: 1,
    events.TOPIC_SIM_CONTROL: 1,
}


def main():
    kwargs = {"bootstrap_servers": os.environ["KAFKA_BOOTSTRAP"].split(",")}
    region = os.environ.get("KAFKA_IAM_REGION")
    if region:
        kwargs.update(security_protocol="SASL_SSL", sasl_mechanism="OAUTHBEARER",
                      sasl_oauth_token_provider=_MskIamTokenProvider(region))
    replication = int(os.environ.get("REPLICATION_FACTOR", "2"))
    admin = KafkaAdminClient(**kwargs)
    existing = set(admin.list_topics())
    for name, partitions in TOPICS.items():
        if name in existing:
            print(f"exists: {name}")
            continue
        try:
            admin.create_topics([NewTopic(name, partitions, replication)])
            print(f"created: {name} partitions={partitions} replication={replication}")
        except TopicAlreadyExistsError:
            print(f"exists: {name}")
    admin.close()


if __name__ == "__main__":
    main()
