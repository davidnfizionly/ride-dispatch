"""Kafka producer factory: plaintext for local Docker, IAM (SASL OAUTHBEARER) for MSK."""
import json
import os


class _MskIamTokenProvider:
    def __init__(self, region):
        self._region = region

    def token(self):
        from aws_msk_iam_sasl_signer import MSKAuthTokenProvider
        token, _expiry_ms = MSKAuthTokenProvider.generate_auth_token(self._region)
        return token


def make_producer(bootstrap=None, iam_region=None, **extra):
    """KAFKA_BOOTSTRAP and, for MSK, KAFKA_IAM_REGION come from the environment."""
    from kafka import KafkaProducer

    bootstrap = bootstrap or os.environ["KAFKA_BOOTSTRAP"]
    iam_region = iam_region or os.environ.get("KAFKA_IAM_REGION")
    kwargs = dict(
        bootstrap_servers=bootstrap.split(","),
        key_serializer=lambda k: k.encode() if k is not None else None,
        value_serializer=lambda v: json.dumps(v).encode(),
        linger_ms=20,
        acks=1,
    )
    if iam_region:
        kwargs.update(
            security_protocol="SASL_SSL",
            sasl_mechanism="OAUTHBEARER",
            sasl_oauth_token_provider=_MskIamTokenProvider(iam_region),
        )
    kwargs.update(extra)
    return KafkaProducer(**kwargs)


def make_consumer(topics, group_id, bootstrap=None, iam_region=None, **extra):
    from kafka import KafkaConsumer

    bootstrap = bootstrap or os.environ["KAFKA_BOOTSTRAP"]
    iam_region = iam_region or os.environ.get("KAFKA_IAM_REGION")
    kwargs = dict(
        bootstrap_servers=bootstrap.split(","),
        group_id=group_id,
        value_deserializer=lambda v: json.loads(v),
        auto_offset_reset="latest",
        enable_auto_commit=True,
    )
    if iam_region:
        kwargs.update(
            security_protocol="SASL_SSL",
            sasl_mechanism="OAUTHBEARER",
            sasl_oauth_token_provider=_MskIamTokenProvider(iam_region),
        )
    kwargs.update(extra)
    consumer = KafkaConsumer(**kwargs)
    consumer.subscribe(topics)
    return consumer
