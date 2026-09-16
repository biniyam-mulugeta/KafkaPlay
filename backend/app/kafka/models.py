"""API-facing Kafka models.

Deliberately decoupled from confluent_kafka types so the API layer never
imports librdkafka classes and the schema stays stable if the client changes.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.kafka.errors import Degraded


class ClusterMode(StrEnum):
    KRAFT = "kraft"
    ZOOKEEPER = "zookeeper"
    UNKNOWN = "unknown"


class Capability(StrEnum):
    """Admin operations that brokers differ on.

    Probed once per cluster so the UI can grey out what will not work rather
    than offering a button that fails.
    """

    DESCRIBE_CLUSTER = "describe_cluster"
    DESCRIBE_CONFIGS = "describe_configs"
    ALTER_CONFIGS = "alter_configs"
    CREATE_TOPICS = "create_topics"
    DELETE_TOPICS = "delete_topics"
    CREATE_PARTITIONS = "create_partitions"
    LIST_GROUPS = "list_groups"
    DESCRIBE_GROUPS = "describe_groups"
    DELETE_GROUPS = "delete_groups"
    LIST_GROUP_OFFSETS = "list_group_offsets"
    ALTER_GROUP_OFFSETS = "alter_group_offsets"
    LIST_OFFSETS = "list_offsets"
    DESCRIBE_ACLS = "describe_acls"
    ALTER_ACLS = "alter_acls"
    ELECT_LEADERS = "elect_leaders"
    DESCRIBE_LOG_DIRS = "describe_log_dirs"


class Broker(BaseModel):
    id: int
    host: str
    port: int
    rack: str | None = None
    is_controller: bool = False


class ClusterInfo(BaseModel):
    name: str
    label: str
    cluster_id: str | None = None
    mode: ClusterMode = ClusterMode.UNKNOWN
    brokers: list[Broker] = Field(default_factory=list)
    controller_id: int | None = None
    topic_count: int = 0
    # Internal topics (__consumer_offsets and friends) are counted separately;
    # most operators do not want them in the headline number.
    internal_topic_count: int = 0
    partition_count: int = 0
    under_replicated_partitions: int = 0
    offline_partitions: int = 0
    capabilities: list[Capability] = Field(default_factory=list)
    read_only: bool = False
    degraded: Degraded | None = None


class PartitionInfo(BaseModel):
    partition: int
    leader: int | None = None
    replicas: list[int] = Field(default_factory=list)
    in_sync_replicas: list[int] = Field(default_factory=list)
    low_watermark: int | None = None
    high_watermark: int | None = None

    @property
    def message_count(self) -> int | None:
        """Approximate: high minus low ignores compaction and transactions."""
        if self.low_watermark is None or self.high_watermark is None:
            return None
        return max(0, self.high_watermark - self.low_watermark)

    @property
    def is_under_replicated(self) -> bool:
        return len(self.in_sync_replicas) < len(self.replicas)

    @property
    def is_offline(self) -> bool:
        return self.leader is None


class TopicSummary(BaseModel):
    name: str
    partition_count: int
    replication_factor: int
    is_internal: bool = False
    under_replicated_partitions: int = 0
    offline_partitions: int = 0
    message_count: int | None = None
    # Populated from configs when requested; listing stays cheap by default.
    retention_ms: int | None = None
    cleanup_policy: str | None = None


class TopicListResponse(BaseModel):
    topics: list[TopicSummary] = Field(default_factory=list)
    degraded: Degraded | None = None


class ConfigEntry(BaseModel):
    name: str
    value: str | None = None
    source: str
    is_default: bool
    is_read_only: bool = False
    is_sensitive: bool = False
    documentation: str | None = None


class TopicDetail(BaseModel):
    name: str
    is_internal: bool = False
    partitions: list[PartitionInfo] = Field(default_factory=list)
    replication_factor: int = 0
    message_count: int | None = None
    consumer_groups: list[str] = Field(default_factory=list)
    degraded: Degraded | None = None


class TopicConfigResponse(BaseModel):
    topic: str
    configs: list[ConfigEntry] = Field(default_factory=list)
    degraded: Degraded | None = None


class GroupState(StrEnum):
    UNKNOWN = "unknown"
    PREPARING_REBALANCE = "preparing_rebalance"
    COMPLETING_REBALANCE = "completing_rebalance"
    STABLE = "stable"
    DEAD = "dead"
    EMPTY = "empty"


class GroupMemberAssignment(BaseModel):
    topic: str
    partitions: list[int] = Field(default_factory=list)


class GroupMember(BaseModel):
    member_id: str
    client_id: str | None = None
    host: str | None = None
    group_instance_id: str | None = None
    assignments: list[GroupMemberAssignment] = Field(default_factory=list)


class GroupSummary(BaseModel):
    group_id: str
    state: GroupState = GroupState.UNKNOWN
    is_simple: bool = False
    member_count: int = 0
    topics: list[str] = Field(default_factory=list)
    total_lag: int | None = None


class GroupListResponse(BaseModel):
    groups: list[GroupSummary] = Field(default_factory=list)
    degraded: Degraded | None = None


class PartitionLag(BaseModel):
    topic: str
    partition: int
    current_offset: int | None = None
    high_watermark: int | None = None
    lag: int | None = None
    member_id: str | None = None

    @classmethod
    def build(
        cls,
        topic: str,
        partition: int,
        current_offset: int | None,
        high_watermark: int | None,
        member_id: str | None = None,
    ) -> PartitionLag:
        lag: int | None = None
        # A group that has never committed reports -1; that is "no commit",
        # not a lag of minus one.
        if current_offset is not None and current_offset >= 0 and high_watermark is not None:
            lag = max(0, high_watermark - current_offset)
        return cls(
            topic=topic,
            partition=partition,
            current_offset=current_offset,
            high_watermark=high_watermark,
            lag=lag,
            member_id=member_id,
        )


class GroupDetail(BaseModel):
    group_id: str
    state: GroupState = GroupState.UNKNOWN
    is_simple: bool = False
    coordinator_id: int | None = None
    partition_assignor: str | None = None
    members: list[GroupMember] = Field(default_factory=list)
    lags: list[PartitionLag] = Field(default_factory=list)
    total_lag: int | None = None
    degraded: Degraded | None = None


class ReplicaCell(BaseModel):
    """One topic-partition's placement, for the replication matrix."""

    topic: str
    partition: int
    leader: int | None = None
    replicas: list[int] = Field(default_factory=list)
    in_sync_replicas: list[int] = Field(default_factory=list)
    is_under_replicated: bool = False
    is_offline: bool = False
    min_insync_replicas: int | None = None
    # True when in-sync count has fallen to min.insync.replicas: the next
    # failure stops producers with acks=all.
    at_min_isr: bool = False


class BrokerLoad(BaseModel):
    broker_id: int
    leader_count: int = 0
    replica_count: int = 0


class ReplicationResponse(BaseModel):
    cells: list[ReplicaCell] = Field(default_factory=list)
    broker_load: list[BrokerLoad] = Field(default_factory=list)
    under_replicated_count: int = 0
    offline_count: int = 0
    at_min_isr_count: int = 0
    # Partitions whose leader is not the first replica: preferred-leader
    # election would rebalance them.
    non_preferred_leader_count: int = 0
    degraded: Degraded | None = None
