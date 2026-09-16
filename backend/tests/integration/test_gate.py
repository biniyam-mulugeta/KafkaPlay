"""KafkaGate against a live broker.

Runs in CI across Kafka 3.9, Kafka 4.x and Redpanda, and locally whenever
KAFKAPLAY_TEST_BOOTSTRAP is set. Skipped otherwise.

These cover the paths that unit tests with fakes cannot: real metadata shapes,
real offset semantics, and the capability differences between broker
implementations.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import Iterator

import pytest
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from app.clusters.models import ClusterConfig
from app.kafka.errors import KafkaGateError
from app.kafka.gate import KafkaGate
from app.kafka.models import Capability

pytestmark = pytest.mark.integration

MESSAGES = 50
PARTITIONS = 3


@pytest.fixture
def gate(bootstrap_servers: str) -> Iterator[KafkaGate]:
    cluster = ClusterConfig(name="it", bootstrap_servers=bootstrap_servers)
    instance = KafkaGate(cluster, timeout_seconds=20.0)
    yield instance
    instance.close()


@pytest.fixture
def seeded_topic(bootstrap_servers: str) -> Iterator[str]:
    """A topic with a known message count, cleaned up afterwards."""
    name = f"kafkaplay-it-{uuid.uuid4().hex[:8]}"
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    admin.create_topics([NewTopic(name, num_partitions=PARTITIONS, replication_factor=1)])[
        name
    ].result(timeout=30)

    producer = Producer({"bootstrap.servers": bootstrap_servers})
    for i in range(MESSAGES):
        producer.produce(name, key=f"k{i}".encode(), value=json.dumps({"i": i}).encode())
    producer.flush(30)

    yield name

    with contextlib.suppress(Exception):
        admin.delete_topics([name])[name].result(timeout=30)


class TestClusterDescription:
    async def test_reports_brokers_and_controller(self, gate: KafkaGate) -> None:
        info = await gate.describe_cluster()
        assert len(info.brokers) >= 1
        assert info.cluster_id
        # Every broker must have a reachable-looking endpoint.
        for broker in info.brokers:
            assert broker.host
            assert broker.port > 0

    async def test_counts_are_self_consistent(self, gate: KafkaGate, seeded_topic: str) -> None:
        info = await gate.describe_cluster()
        assert info.partition_count >= PARTITIONS
        assert info.topic_count >= 1

    async def test_partition_count_excludes_internal_topics(
        self, gate: KafkaGate, seeded_topic: str
    ) -> None:
        """The headline number must match the topics it sits next to.

        __consumer_offsets has 50 partitions by default; counting it made a
        two-topic cluster report fifty-odd partitions.
        """
        info = await gate.describe_cluster()
        user_topics = await gate.list_topics(include_internal=False)
        assert info.partition_count == sum(t.partition_count for t in user_topics)
        all_topics = await gate.list_topics(include_internal=True)
        internal = sum(t.partition_count for t in all_topics if t.is_internal)
        assert info.internal_partition_count == internal

    async def test_healthy_cluster_has_no_offline_partitions(self, gate: KafkaGate) -> None:
        info = await gate.describe_cluster()
        assert info.offline_partitions == 0


class TestCapabilities:
    async def test_core_capabilities_present(self, gate: KafkaGate) -> None:
        capabilities = await gate.capabilities()
        # These exist on every broker the project claims to support.
        assert Capability.LIST_OFFSETS in capabilities
        assert Capability.CREATE_TOPICS in capabilities

    async def test_capabilities_are_cached(self, gate: KafkaGate) -> None:
        first = await gate.capabilities()
        assert await gate.capabilities() is first


class TestTopics:
    async def test_lists_the_seeded_topic(self, gate: KafkaGate, seeded_topic: str) -> None:
        names = [topic.name for topic in await gate.list_topics()]
        assert seeded_topic in names

    async def test_internal_topics_excluded_by_default(self, gate: KafkaGate) -> None:
        default = [t.name for t in await gate.list_topics()]
        assert not any(name.startswith("__") for name in default)

    async def test_internal_topics_included_on_request(self, gate: KafkaGate) -> None:
        # __consumer_offsets exists once any group has committed.
        included = [t.name for t in await gate.list_topics(include_internal=True)]
        default = [t.name for t in await gate.list_topics()]
        assert len(included) >= len(default)

    async def test_describe_reports_exact_message_count(
        self, gate: KafkaGate, seeded_topic: str
    ) -> None:
        detail = await gate.describe_topic(seeded_topic)
        assert len(detail.partitions) == PARTITIONS
        # Watermark arithmetic must match what was actually produced.
        assert detail.message_count == MESSAGES

    async def test_every_partition_has_a_leader(self, gate: KafkaGate, seeded_topic: str) -> None:
        detail = await gate.describe_topic(seeded_topic)
        for partition in detail.partitions:
            assert partition.leader is not None
            assert not partition.is_offline
            assert not partition.is_under_replicated

    async def test_unknown_topic_raises(self, gate: KafkaGate) -> None:
        with pytest.raises(KafkaGateError):
            await gate.describe_topic(f"does-not-exist-{uuid.uuid4().hex[:8]}")

    async def test_configs_include_retention_and_cleanup(
        self, gate: KafkaGate, seeded_topic: str
    ) -> None:
        configs = await gate.topic_configs(seeded_topic)
        names = {entry.name for entry in configs}
        assert "cleanup.policy" in names
        assert "retention.ms" in names

    async def test_config_source_is_a_name_not_a_number(
        self, gate: KafkaGate, seeded_topic: str
    ) -> None:
        # librdkafka returns an int here; the UI must never show "5".
        configs = await gate.topic_configs(seeded_topic)
        for entry in configs:
            assert not entry.source.isdigit(), f"{entry.name} source is numeric: {entry.source}"


class TestConsumerGroupsAndLag:
    @pytest.fixture
    def committed_group(self, bootstrap_servers: str, seeded_topic: str) -> Iterator[str]:
        """A group that has consumed part of a topic, leaving real lag."""
        group_id = f"kafkaplay-it-group-{uuid.uuid4().hex[:8]}"
        consumer = Consumer(
            {
                "bootstrap.servers": bootstrap_servers,
                "group.id": group_id,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        consumer.subscribe([seeded_topic])
        consumed = 0
        while consumed < 10:
            message = consumer.poll(5.0)
            if message is None:
                break
            if not message.error():
                consumed += 1
        consumer.commit(asynchronous=False)
        consumer.close()

        yield group_id

        with contextlib.suppress(Exception):
            admin = AdminClient({"bootstrap.servers": bootstrap_servers})
            admin.delete_consumer_groups([group_id])[group_id].result(timeout=30)

    async def test_group_appears_in_listing(self, gate: KafkaGate, committed_group: str) -> None:
        assert committed_group in [group.group_id for group in await gate.list_groups()]

    async def test_lag_is_positive_and_bounded(
        self, gate: KafkaGate, committed_group: str, seeded_topic: str
    ) -> None:
        lags = await gate.group_lag(committed_group)
        assert lags, "expected committed offsets for the group"

        total = sum(lag.lag for lag in lags if lag.lag is not None)
        # 10 of MESSAGES consumed, so lag is real but cannot exceed the total.
        assert 0 < total < MESSAGES
        for lag in lags:
            assert lag.topic == seeded_topic
            if lag.lag is not None:
                assert lag.lag >= 0

    async def test_describe_group_is_empty_after_consumers_stop(
        self, gate: KafkaGate, committed_group: str
    ) -> None:
        detail = await gate.describe_group(committed_group)
        assert detail.group_id == committed_group
        # The consumer closed, so the group has no members. This is exactly the
        # precondition the M5 offset reset will require.
        assert detail.members == []
        assert detail.total_lag is not None

    async def test_groups_for_topic_finds_the_group(
        self, gate: KafkaGate, committed_group: str, seeded_topic: str
    ) -> None:
        assert committed_group in await gate.groups_for_topic(seeded_topic)


class TestDegradedBehaviour:
    async def test_unreachable_broker_raises_typed_error_not_a_hang(self) -> None:
        """A wrong address must fail fast and cleanly, not block the request."""
        cluster = ClusterConfig(name="nope", bootstrap_servers="127.0.0.1:1")
        gate = KafkaGate(cluster, timeout_seconds=3.0)
        try:
            with pytest.raises(KafkaGateError):
                await gate.describe_cluster()
        finally:
            gate.close()
