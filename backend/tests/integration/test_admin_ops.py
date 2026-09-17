"""Mutating operations against a live broker.

The safety properties matter more than the happy paths here: a dry run must
not change anything, and an offset reset must refuse to run under a live
consumer.
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
from app.kafka.admin_ops import KafkaAdminOps, ResetTo
from app.kafka.errors import KafkaGateError
from app.kafka.gate import KafkaGate

pytestmark = pytest.mark.integration

MESSAGES = 40


@pytest.fixture
def gate(bootstrap_servers: str) -> Iterator[KafkaGate]:
    instance = KafkaGate(
        ClusterConfig(name="it", bootstrap_servers=bootstrap_servers), timeout_seconds=20.0
    )
    yield instance
    instance.close()


@pytest.fixture
def ops(gate: KafkaGate) -> KafkaAdminOps:
    return KafkaAdminOps(gate)


@pytest.fixture
def temp_topic(bootstrap_servers: str) -> Iterator[str]:
    name = f"offsetscope-admin-{uuid.uuid4().hex[:8]}"
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    admin.create_topics([NewTopic(name, num_partitions=2, replication_factor=1)])[name].result(
        timeout=30
    )
    producer = Producer({"bootstrap.servers": bootstrap_servers})
    for i in range(MESSAGES):
        producer.produce(name, key=f"k{i}".encode(), value=json.dumps({"i": i}).encode())
    producer.flush(30)

    yield name

    with contextlib.suppress(Exception):
        admin.delete_topics([name])[name].result(timeout=30)


class TestTopicLifecycle:
    async def test_create_describe_delete(self, ops: KafkaAdminOps, gate: KafkaGate) -> None:
        name = f"offsetscope-life-{uuid.uuid4().hex[:8]}"
        await ops.create_topic(name, partitions=3, replication_factor=1)

        detail = await gate.describe_topic(name, with_watermarks=False)
        assert len(detail.partitions) == 3

        await ops.delete_topic(name)

    async def test_create_with_configs(self, ops: KafkaAdminOps, gate: KafkaGate) -> None:
        name = f"offsetscope-cfg-{uuid.uuid4().hex[:8]}"
        await ops.create_topic(
            name, partitions=1, replication_factor=1, configs={"retention.ms": "60000"}
        )
        try:
            configs = await gate.topic_configs(name)
            retention = next(entry for entry in configs if entry.name == "retention.ms")
            assert retention.value == "60000"
            # A value we set explicitly must not be reported as a default.
            assert not retention.is_default
        finally:
            await ops.delete_topic(name)

    async def test_add_partitions(
        self, ops: KafkaAdminOps, gate: KafkaGate, temp_topic: str
    ) -> None:
        await ops.add_partitions(temp_topic, total=4)
        detail = await gate.describe_topic(temp_topic, with_watermarks=False)
        assert len(detail.partitions) == 4


class TestConfigChanges:
    async def test_preview_reports_current_and_new(
        self, ops: KafkaAdminOps, temp_topic: str
    ) -> None:
        changes = await ops.preview_config_change(temp_topic, {"retention.ms": "120000"})
        assert len(changes) == 1
        assert changes[0].name == "retention.ms"
        assert changes[0].new_value == "120000"
        assert changes[0].current_value != "120000"

    async def test_preview_does_not_change_anything(
        self, ops: KafkaAdminOps, gate: KafkaGate, temp_topic: str
    ) -> None:
        before = {e.name: e.value for e in await gate.topic_configs(temp_topic)}
        await ops.preview_config_change(temp_topic, {"retention.ms": "999000"})
        after = {e.name: e.value for e in await gate.topic_configs(temp_topic)}
        assert before == after

    async def test_apply_changes_the_value(
        self, ops: KafkaAdminOps, gate: KafkaGate, temp_topic: str
    ) -> None:
        await ops.alter_topic_configs(temp_topic, {"retention.ms": "120000"})
        configs = {e.name: e.value for e in await gate.topic_configs(temp_topic)}
        assert configs["retention.ms"] == "120000"


@pytest.fixture
def lagging_group(bootstrap_servers: str, temp_topic: str) -> Iterator[str]:
    """A group with committed offsets and no live members."""
    group_id = f"offsetscope-reset-{uuid.uuid4().hex[:8]}"
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([temp_topic])
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


class TestOffsetResetPreview:
    async def test_earliest_reports_replay_count(
        self, ops: KafkaAdminOps, lagging_group: str
    ) -> None:
        preview = await ops.preview_offset_reset(lagging_group, reset_to=ResetTo.EARLIEST)
        assert preview.changes
        assert all(
            change.target_offset == (change.low_watermark or 0) for change in preview.changes
        )
        # Rewinding to the start replays what was already consumed.
        assert preview.total_replayed > 0
        assert preview.total_skipped == 0

    async def test_latest_reports_skip_count(self, ops: KafkaAdminOps, lagging_group: str) -> None:
        preview = await ops.preview_offset_reset(lagging_group, reset_to=ResetTo.LATEST)
        assert preview.total_skipped > 0
        assert preview.total_replayed == 0

    async def test_preview_does_not_move_offsets(
        self, ops: KafkaAdminOps, gate: KafkaGate, lagging_group: str
    ) -> None:
        before = {
            (lag.topic, lag.partition): lag.current_offset
            for lag in await gate.group_lag(lagging_group)
        }
        await ops.preview_offset_reset(lagging_group, reset_to=ResetTo.EARLIEST)
        after = {
            (lag.topic, lag.partition): lag.current_offset
            for lag in await gate.group_lag(lagging_group)
        }
        assert before == after

    async def test_target_is_clamped_to_the_retained_range(
        self, ops: KafkaAdminOps, lagging_group: str
    ) -> None:
        # Asking for an absurd offset must not produce one the broker rejects.
        preview = await ops.preview_offset_reset(
            lagging_group, reset_to=ResetTo.OFFSET, target_offset=10_000_000
        )
        for change in preview.changes:
            assert change.high_watermark is not None
            assert change.target_offset <= change.high_watermark

    async def test_shift_is_relative_to_current(
        self, ops: KafkaAdminOps, lagging_group: str
    ) -> None:
        preview = await ops.preview_offset_reset(lagging_group, reset_to=ResetTo.SHIFT, shift_by=-5)
        for change in preview.changes:
            if change.current_offset is not None and change.current_offset >= 5:
                assert change.target_offset == change.current_offset - 5

    async def test_inactive_group_is_safe(self, ops: KafkaAdminOps, lagging_group: str) -> None:
        preview = await ops.preview_offset_reset(lagging_group, reset_to=ResetTo.EARLIEST)
        assert preview.member_count == 0
        assert preview.is_safe


class TestOffsetResetApply:
    async def test_reset_to_earliest_moves_offsets(
        self, ops: KafkaAdminOps, gate: KafkaGate, lagging_group: str
    ) -> None:
        preview = await ops.preview_offset_reset(lagging_group, reset_to=ResetTo.EARLIEST)
        await ops.apply_offset_reset(preview)

        after = await gate.group_lag(lagging_group)
        for lag in after:
            assert lag.current_offset in (0, None)

    async def test_refuses_while_a_consumer_is_live(
        self,
        ops: KafkaAdminOps,
        bootstrap_servers: str,
        temp_topic: str,
        lagging_group: str,
    ) -> None:
        """The central safety property of the whole feature.

        Kafka itself will happily reset offsets under a running consumer,
        which silently skips or duplicates records. The console must not.
        """
        consumer = Consumer(
            {
                "bootstrap.servers": bootstrap_servers,
                "group.id": lagging_group,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        consumer.subscribe([temp_topic])
        # Poll until the group actually has a member.
        for _ in range(20):
            consumer.poll(1.0)
            preview = await ops.preview_offset_reset(lagging_group, reset_to=ResetTo.EARLIEST)
            if preview.member_count > 0:
                break

        try:
            assert preview.member_count > 0, "expected a live member for this test"
            assert not preview.is_safe
            with pytest.raises(KafkaGateError, match="active"):
                await ops.apply_offset_reset(preview)
        finally:
            consumer.close()


class TestGroupDeletion:
    async def test_delete_inactive_group(self, ops: KafkaAdminOps, lagging_group: str) -> None:
        await ops.delete_group(lagging_group)

    async def test_refuses_to_delete_an_active_group(
        self, ops: KafkaAdminOps, bootstrap_servers: str, temp_topic: str, lagging_group: str
    ) -> None:
        consumer = Consumer(
            {
                "bootstrap.servers": bootstrap_servers,
                "group.id": lagging_group,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        consumer.subscribe([temp_topic])
        for _ in range(20):
            consumer.poll(1.0)
            detail = await ops._gate.describe_group(lagging_group, with_lag=False)
            if detail.members:
                break
        try:
            with pytest.raises(KafkaGateError, match="member"):
                await ops.delete_group(lagging_group)
        finally:
            consumer.close()
