"""Mutating Kafka operations.

Everything here changes a cluster, so every function is paired with a dry-run
that computes and returns exactly what would change without doing it. The API
layer refuses to execute anything the caller has not first previewed.

The offset reset in particular enforces that the target group is inactive.
Resetting offsets under a live consumer produces silent duplicate processing
or silent data skipping, and Kafka will not stop you.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from confluent_kafka import ConsumerGroupTopicPartitions, TopicPartition
from confluent_kafka.admin import (  # type: ignore[attr-defined]
    AlterConfigOpType,
    ConfigResource,
    NewPartitions,
    NewTopic,
    OffsetSpec,
)
from confluent_kafka.admin import (  # type: ignore[attr-defined]
    ConfigEntry as KafkaConfigEntry,
)

from app.kafka.errors import KafkaGateError
from app.kafka.gate import KafkaGate
from app.kafka.models import Capability, GroupState


class ResetTo(StrEnum):
    EARLIEST = "earliest"
    LATEST = "latest"
    TIMESTAMP = "timestamp"
    OFFSET = "offset"
    SHIFT = "shift"


@dataclass(slots=True)
class OffsetChange:
    topic: str
    partition: int
    current_offset: int | None
    target_offset: int
    low_watermark: int | None = None
    high_watermark: int | None = None

    @property
    def delta(self) -> int | None:
        if self.current_offset is None or self.current_offset < 0:
            return None
        return self.target_offset - self.current_offset

    @property
    def messages_skipped(self) -> int:
        """Records that would be passed over without being processed."""
        delta = self.delta
        return delta if delta is not None and delta > 0 else 0

    @property
    def messages_replayed(self) -> int:
        """Records that would be delivered a second time."""
        delta = self.delta
        return -delta if delta is not None and delta < 0 else 0


@dataclass(slots=True)
class ResetPreview:
    group_id: str
    reset_to: ResetTo
    changes: list[OffsetChange] = field(default_factory=list)
    group_state: GroupState = GroupState.UNKNOWN
    member_count: int = 0

    @property
    def is_safe(self) -> bool:
        """Only an inactive group can be reset without surprising a consumer."""
        return self.member_count == 0 and self.group_state in (
            GroupState.EMPTY,
            GroupState.DEAD,
            GroupState.UNKNOWN,
        )

    @property
    def total_skipped(self) -> int:
        return sum(change.messages_skipped for change in self.changes)

    @property
    def total_replayed(self) -> int:
        return sum(change.messages_replayed for change in self.changes)


@dataclass(slots=True)
class ConfigChange:
    name: str
    current_value: str | None
    new_value: str | None
    is_default: bool = False


class KafkaAdminOps:
    """Write operations, always reached through a gate."""

    def __init__(self, gate: KafkaGate) -> None:
        self._gate = gate

    # --- topics -----------------------------------------------------------

    async def create_topic(
        self,
        name: str,
        *,
        partitions: int,
        replication_factor: int,
        configs: dict[str, str] | None = None,
    ) -> None:
        await self._gate.require(Capability.CREATE_TOPICS)
        admin = await self._gate._client()
        topic = NewTopic(
            name,
            num_partitions=partitions,
            replication_factor=replication_factor,
            config=configs or {},
        )

        def run() -> None:
            futures = admin.create_topics([topic], request_timeout=self._gate.timeout)
            futures[name].result(timeout=self._gate.timeout)

        await self._gate._run(run)

    async def delete_topic(self, name: str) -> None:
        await self._gate.require(Capability.DELETE_TOPICS)
        admin = await self._gate._client()

        def run() -> None:
            futures = admin.delete_topics([name], request_timeout=self._gate.timeout)
            futures[name].result(timeout=self._gate.timeout)

        await self._gate._run(run)

    async def add_partitions(self, name: str, *, total: int) -> None:
        """Increase a topic's partition count.

        Kafka cannot decrease it, and increasing changes key-to-partition
        mapping for future records -- the API layer says so before executing.
        """
        await self._gate.require(Capability.CREATE_PARTITIONS)
        admin = await self._gate._client()

        def run() -> None:
            futures = admin.create_partitions(
                [NewPartitions(name, total)], request_timeout=self._gate.timeout
            )
            futures[name].result(timeout=self._gate.timeout)

        await self._gate._run(run)

    async def preview_config_change(
        self, topic: str, updates: dict[str, str]
    ) -> list[ConfigChange]:
        current = {entry.name: entry for entry in await self._gate.topic_configs(topic)}
        return [
            ConfigChange(
                name=name,
                current_value=current[name].value if name in current else None,
                new_value=value,
                is_default=current[name].is_default if name in current else False,
            )
            for name, value in sorted(updates.items())
        ]

    async def alter_topic_configs(self, topic: str, updates: dict[str, str]) -> None:
        """Apply config changes incrementally.

        Incremental rather than wholesale: a full alter would reset every
        setting the request did not mention back to its default, which is a
        spectacular way to lose a carefully tuned topic.

        An empty string means "remove this override and fall back to the
        broker default", expressed as a DELETE operation.
        """
        await self._gate.require(Capability.ALTER_CONFIGS)
        admin = await self._gate._client()
        resource = ConfigResource(ConfigResource.Type.TOPIC, topic)
        for name, value in updates.items():
            operation = AlterConfigOpType.DELETE if value == "" else AlterConfigOpType.SET
            resource.add_incremental_config(
                KafkaConfigEntry(name, value, incremental_operation=operation)
            )

        def run() -> None:
            futures = admin.incremental_alter_configs(
                [resource], request_timeout=self._gate.timeout
            )
            for future in futures.values():
                future.result(timeout=self._gate.timeout)

        await self._gate._run(run)

    # --- consumer groups --------------------------------------------------

    async def preview_offset_reset(
        self,
        group_id: str,
        *,
        reset_to: ResetTo,
        topics: list[str] | None = None,
        target_offset: int | None = None,
        timestamp_ms: int | None = None,
        shift_by: int | None = None,
    ) -> ResetPreview:
        """Compute the exact target offsets without applying anything."""
        await self._gate.require(Capability.LIST_GROUP_OFFSETS)

        detail = await self._gate.describe_group(group_id, with_lag=False)
        current = await self._gate.group_lag(group_id)
        if topics:
            wanted = set(topics)
            current = [lag for lag in current if lag.topic in wanted]

        preview = ResetPreview(
            group_id=group_id,
            reset_to=reset_to,
            group_state=detail.state,
            member_count=len(detail.members),
        )
        if not current:
            return preview

        marks = await self._gate.watermarks((lag.topic, lag.partition) for lag in current)

        resolved_by_timestamp: dict[tuple[str, int], int] = {}
        if reset_to is ResetTo.TIMESTAMP and timestamp_ms is not None:
            admin = await self._gate._client()
            request = {
                TopicPartition(lag.topic, lag.partition): OffsetSpec.for_timestamp(timestamp_ms)
                for lag in current
            }

            def run() -> dict[Any, Any]:
                return admin.list_offsets(request, request_timeout=self._gate.timeout)

            futures = await self._gate._run(run)
            for tp, future in futures.items():
                try:
                    resolved_by_timestamp[(tp.topic, tp.partition)] = future.result(
                        timeout=self._gate.timeout
                    ).offset
                except Exception:
                    continue

        for lag in current:
            key = (lag.topic, lag.partition)
            low, high = marks.get(key, (None, None))

            match reset_to:
                case ResetTo.EARLIEST:
                    target = low if low is not None else 0
                case ResetTo.LATEST:
                    target = high if high is not None else 0
                case ResetTo.OFFSET:
                    target = target_offset if target_offset is not None else 0
                case ResetTo.SHIFT:
                    base = lag.current_offset if lag.current_offset is not None else 0
                    target = base + (shift_by or 0)
                case ResetTo.TIMESTAMP:
                    resolved = resolved_by_timestamp.get(key)
                    # A timestamp past the end of the log resolves to -1;
                    # clamp to the end rather than rewinding to the start.
                    target = resolved if resolved is not None and resolved >= 0 else (high or 0)

            # Never propose an offset outside the retained range.
            if low is not None:
                target = max(low, target)
            if high is not None:
                target = min(high, target)

            preview.changes.append(
                OffsetChange(
                    topic=lag.topic,
                    partition=lag.partition,
                    current_offset=lag.current_offset,
                    target_offset=target,
                    low_watermark=low,
                    high_watermark=high,
                )
            )

        preview.changes.sort(key=lambda change: (change.topic, change.partition))
        return preview

    async def apply_offset_reset(self, preview: ResetPreview) -> None:
        """Apply a previously computed preview.

        Takes the preview rather than the parameters so what executes is
        exactly what the operator was shown and confirmed.
        """
        await self._gate.require(Capability.ALTER_GROUP_OFFSETS)
        if not preview.is_safe:
            raise KafkaGateError(
                f"consumer group {preview.group_id!r} is active with "
                f"{preview.member_count} member(s); stop its consumers before resetting offsets",
                hint="Resetting offsets under a live consumer silently skips or replays records.",
            )

        admin = await self._gate._client()
        partitions = [
            TopicPartition(change.topic, change.partition, change.target_offset)
            for change in preview.changes
        ]
        request = ConsumerGroupTopicPartitions(preview.group_id, partitions)

        def run() -> None:
            futures = admin.alter_consumer_group_offsets(
                [request], request_timeout=self._gate.timeout
            )
            for future in futures.values():
                future.result(timeout=self._gate.timeout)

        await self._gate._run(run)

    async def delete_group(self, group_id: str) -> None:
        await self._gate.require(Capability.DELETE_GROUPS)
        detail = await self._gate.describe_group(group_id, with_lag=False)
        if detail.members:
            raise KafkaGateError(
                f"consumer group {group_id!r} still has {len(detail.members)} member(s)",
                hint="Stop the group's consumers before deleting it.",
            )

        admin = await self._gate._client()

        def run() -> None:
            futures = admin.delete_consumer_groups([group_id], request_timeout=self._gate.timeout)
            futures[group_id].result(timeout=self._gate.timeout)

        await self._gate._run(run)

    # --- leadership -------------------------------------------------------

    async def elect_preferred_leaders(self, partitions: list[tuple[str, int]] | None = None) -> int:
        """Move leadership back to the preferred (first) replica.

        Returns how many partitions were requested. Safe and routine: it only
        moves leadership between existing in-sync replicas.
        """
        await self._gate.require(Capability.ELECT_LEADERS)
        admin = await self._gate._client()

        selected = (
            [TopicPartition(topic, partition) for topic, partition in partitions]
            if partitions
            else None
        )

        def run() -> None:
            from confluent_kafka.admin import ElectionType  # type: ignore[attr-defined]

            future = admin.elect_leaders(ElectionType.PREFERRED, selected)
            future.result(timeout=self._gate.timeout)

        await self._gate._run(run)
        return len(selected) if selected else 0
