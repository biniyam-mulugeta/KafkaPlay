"""The only place that talks to Kafka.

Three rules hold for everything in this module:

1. librdkafka blocks, so every call runs in a thread pool.
2. Every call has a timeout. A hung broker must not hang a request.
3. Consumer lag comes from the AdminClient, never from a shadow consumer.
   Running a consumer to measure lag would add group churn and broker load
   for something the offsets API already answers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

from confluent_kafka import ConsumerGroupTopicPartitions, TopicPartition
from confluent_kafka.admin import (  # type: ignore[attr-defined]
    AdminClient,
    ConfigResource,
    ConfigSource,
    OffsetSpec,
)

from app.clusters.models import ClusterConfig
from app.kafka.errors import (
    KafkaGateError,
    UnsupportedOperationError,
    translate_kafka_error,
)
from app.kafka.models import (
    Broker,
    Capability,
    ClusterInfo,
    ClusterMode,
    ConfigEntry,
    GroupDetail,
    GroupMember,
    GroupMemberAssignment,
    GroupState,
    GroupSummary,
    PartitionInfo,
    PartitionLag,
    TopicDetail,
    TopicSummary,
)
from app.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")

# Topics Kafka manages itself. Shown on request, excluded from headline counts.
INTERNAL_TOPIC_PREFIXES = ("__", "_confluent", "_schemas", "_redpanda")

_GROUP_STATES = {
    "UNKNOWN": GroupState.UNKNOWN,
    "PREPARING_REBALANCING": GroupState.PREPARING_REBALANCE,
    "PREPARING_REBALANCE": GroupState.PREPARING_REBALANCE,
    "COMPLETING_REBALANCING": GroupState.COMPLETING_REBALANCE,
    "COMPLETING_REBALANCE": GroupState.COMPLETING_REBALANCE,
    "STABLE": GroupState.STABLE,
    "DEAD": GroupState.DEAD,
    "EMPTY": GroupState.EMPTY,
}


def _config_source_name(raw: object) -> str:
    """Render librdkafka's numeric config source as a readable name.

    confluent_kafka returns a plain int here, not the ConfigSource enum, so
    "5" would otherwise reach the UI where "DEFAULT_CONFIG" belongs.
    """
    if raw is None:
        return "UNKNOWN_CONFIG"
    name = getattr(raw, "name", None)
    if isinstance(name, str):
        return name
    if isinstance(raw, int):
        try:
            return str(ConfigSource(raw).name)
        except ValueError:
            return str(raw)
    return str(raw)


def is_internal_topic(name: str) -> bool:
    return name.startswith(INTERNAL_TOPIC_PREFIXES)


def build_client_config(cluster: ClusterConfig, timeout_seconds: float) -> dict[str, Any]:
    """Translate a ClusterConfig into librdkafka properties."""
    config: dict[str, Any] = {
        "bootstrap.servers": cluster.bootstrap_servers,
        "client.id": cluster.client_id,
        "security.protocol": str(cluster.security_protocol),
        "socket.timeout.ms": int(timeout_seconds * 1000),
        # Keep failures fast; the UI shows a degraded banner rather than hanging.
        "reconnect.backoff.max.ms": 5000,
    }

    if cluster.tls:
        tls = cluster.tls
        if tls.ca_location:
            config["ssl.ca.location"] = tls.ca_location
        if tls.certificate_location:
            config["ssl.certificate.location"] = tls.certificate_location
        if tls.key_location:
            config["ssl.key.location"] = tls.key_location
        if tls.key_password:
            config["ssl.key.password"] = tls.key_password
        if tls.insecure_skip_verify:
            config["enable.ssl.certificate.verification"] = False
        elif not tls.verify_hostname:
            config["ssl.endpoint.identification.algorithm"] = "none"

    if cluster.sasl:
        sasl = cluster.sasl
        config["sasl.mechanism"] = str(sasl.mechanism)
        if sasl.username:
            config["sasl.username"] = sasl.username
        if sasl.password:
            config["sasl.password"] = sasl.password
        if sasl.oauth_token_endpoint:
            config["sasl.oauthbearer.method"] = "oidc"
            config["sasl.oauthbearer.token.endpoint.url"] = sasl.oauth_token_endpoint
            if sasl.oauth_client_id:
                config["sasl.oauthbearer.client.id"] = sasl.oauth_client_id
            if sasl.oauth_client_secret:
                config["sasl.oauthbearer.client.secret"] = sasl.oauth_client_secret
            if sasl.oauth_scope:
                config["sasl.oauthbearer.scope"] = sasl.oauth_scope
            if sasl.oauth_extensions:
                config["sasl.oauthbearer.extensions"] = ",".join(
                    f"{k}={v}" for k, v in sasl.oauth_extensions.items()
                )

    return config


class KafkaGate:
    """Async facade over a single cluster's AdminClient."""

    def __init__(
        self,
        cluster: ClusterConfig,
        *,
        timeout_seconds: float = 10.0,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self.cluster = cluster
        self.timeout = cluster.request_timeout_seconds or timeout_seconds
        self._executor = executor or ThreadPoolExecutor(
            max_workers=4, thread_name_prefix=f"kafka-{cluster.name}"
        )
        self._owns_executor = executor is None
        self._admin: AdminClient | None = None
        self._admin_lock = asyncio.Lock()
        self._capabilities: set[Capability] | None = None

    async def _client(self) -> AdminClient:
        if self._admin is None:
            async with self._admin_lock:
                if self._admin is None:
                    config = build_client_config(self.cluster, self.timeout)
                    self._admin = await self._run(lambda: AdminClient(config))
        return self._admin

    async def _run(self, fn: Callable[[], T]) -> T:
        """Run a blocking librdkafka call with a hard timeout."""
        loop = asyncio.get_running_loop()
        try:
            # The librdkafka timeout is the primary guard; this is a backstop
            # in case a call ignores it.
            return await asyncio.wait_for(
                loop.run_in_executor(self._executor, fn),
                timeout=self.timeout + 5,
            )
        except TimeoutError as exc:
            raise translate_kafka_error(exc) from exc
        except KafkaGateError:
            raise
        except Exception as exc:
            raise translate_kafka_error(exc) from exc

    def close(self) -> None:
        if self._owns_executor:
            self._executor.shutdown(wait=False)

    # --- metadata ---------------------------------------------------------

    async def _metadata(self, topic: str | None = None) -> Any:
        admin = await self._client()
        return await self._run(lambda: admin.list_topics(topic=topic, timeout=self.timeout))

    async def describe_cluster(self) -> ClusterInfo:
        metadata = await self._metadata()
        controller_id = getattr(metadata, "controller_id", None)

        brokers = [
            Broker(
                id=broker.id,
                host=broker.host,
                port=broker.port,
                rack=getattr(broker, "rack", None),
                is_controller=broker.id == controller_id,
            )
            for broker in metadata.brokers.values()
        ]
        brokers.sort(key=lambda b: b.id)

        topic_count = 0
        internal_count = 0
        partition_count = 0
        under_replicated = 0
        offline = 0

        for name, topic in metadata.topics.items():
            if is_internal_topic(name):
                internal_count += 1
            else:
                topic_count += 1
            for partition in topic.partitions.values():
                partition_count += 1
                if partition.leader < 0:
                    offline += 1
                elif len(partition.isrs) < len(partition.replicas):
                    under_replicated += 1

        return ClusterInfo(
            name=self.cluster.name,
            label=self.cluster.display_name,
            cluster_id=getattr(metadata, "cluster_id", None),
            # A controller id present in metadata means KRaft or a ZK
            # controller; the quorum API in M8 distinguishes them precisely.
            mode=ClusterMode.KRAFT if controller_id is not None else ClusterMode.UNKNOWN,
            brokers=brokers,
            controller_id=(
                controller_id if controller_id is not None and controller_id >= 0 else None
            ),
            topic_count=topic_count,
            internal_topic_count=internal_count,
            partition_count=partition_count,
            under_replicated_partitions=under_replicated,
            offline_partitions=offline,
            capabilities=sorted(await self.capabilities()),
            read_only=self.cluster.read_only,
        )

    async def capabilities(self) -> set[Capability]:
        """Probe which admin APIs this broker actually implements.

        Cheap: it checks for the presence of methods on the client and makes
        one real call for the operations that commonly differ. Results are
        cached for the lifetime of the gate.
        """
        if self._capabilities is not None:
            return self._capabilities

        admin = await self._client()
        found: set[Capability] = set()

        method_map = {
            Capability.DESCRIBE_CLUSTER: "describe_cluster",
            Capability.DESCRIBE_CONFIGS: "describe_configs",
            Capability.ALTER_CONFIGS: "incremental_alter_configs",
            Capability.CREATE_TOPICS: "create_topics",
            Capability.DELETE_TOPICS: "delete_topics",
            Capability.CREATE_PARTITIONS: "create_partitions",
            Capability.LIST_GROUPS: "list_consumer_groups",
            Capability.DESCRIBE_GROUPS: "describe_consumer_groups",
            Capability.DELETE_GROUPS: "delete_consumer_groups",
            Capability.LIST_GROUP_OFFSETS: "list_consumer_group_offsets",
            Capability.ALTER_GROUP_OFFSETS: "alter_consumer_group_offsets",
            Capability.LIST_OFFSETS: "list_offsets",
            Capability.DESCRIBE_ACLS: "describe_acls",
            Capability.ALTER_ACLS: "create_acls",
            Capability.ELECT_LEADERS: "elect_leaders",
            Capability.DESCRIBE_LOG_DIRS: "describe_log_dirs",
        }
        for capability, method in method_map.items():
            if hasattr(admin, method):
                found.add(capability)

        self._capabilities = found
        return found

    async def require(self, capability: Capability) -> None:
        if capability not in await self.capabilities():
            raise UnsupportedOperationError(
                f"this broker does not support {capability}",
                hint="The feature is hidden for clusters that cannot perform it.",
            )

    # --- topics -----------------------------------------------------------

    async def list_topics(self, *, include_internal: bool = False) -> list[TopicSummary]:
        metadata = await self._metadata()
        summaries: list[TopicSummary] = []

        for name, topic in metadata.topics.items():
            internal = is_internal_topic(name)
            if internal and not include_internal:
                continue

            partitions = list(topic.partitions.values())
            under_replicated = sum(
                1 for p in partitions if p.leader >= 0 and len(p.isrs) < len(p.replicas)
            )
            offline = sum(1 for p in partitions if p.leader < 0)
            replication = max((len(p.replicas) for p in partitions), default=0)

            summaries.append(
                TopicSummary(
                    name=name,
                    partition_count=len(partitions),
                    replication_factor=replication,
                    is_internal=internal,
                    under_replicated_partitions=under_replicated,
                    offline_partitions=offline,
                )
            )

        summaries.sort(key=lambda t: t.name)
        return summaries

    async def watermarks(
        self, topic_partitions: Iterable[tuple[str, int]]
    ) -> dict[tuple[str, int], tuple[int | None, int | None]]:
        """Low and high watermarks, batched in two list_offsets calls."""
        pairs = list(topic_partitions)
        if not pairs:
            return {}

        admin = await self._client()
        result: dict[tuple[str, int], tuple[int | None, int | None]] = dict.fromkeys(
            pairs, (None, None)
        )

        async def fetch(spec: OffsetSpec) -> dict[tuple[str, int], int | None]:
            request = {TopicPartition(topic, partition): spec for topic, partition in pairs}
            futures = await self._run(
                lambda: admin.list_offsets(request, request_timeout=self.timeout)
            )
            offsets: dict[tuple[str, int], int | None] = {}
            for tp, future in futures.items():
                try:
                    offsets[(tp.topic, tp.partition)] = future.result(timeout=self.timeout).offset
                except Exception:
                    # One unavailable partition must not void the whole view.
                    offsets[(tp.topic, tp.partition)] = None
            return offsets

        earliest = await fetch(OffsetSpec.earliest())  # type: ignore[no-untyped-call]
        latest = await fetch(OffsetSpec.latest())  # type: ignore[no-untyped-call]
        for pair in pairs:
            result[pair] = (earliest.get(pair), latest.get(pair))
        return result

    async def describe_topic(self, name: str, *, with_watermarks: bool = True) -> TopicDetail:
        metadata = await self._metadata(topic=name)
        topic = metadata.topics.get(name)
        if topic is None or (getattr(topic, "error", None) is not None and not topic.partitions):
            raise KafkaGateError(f"topic {name!r} does not exist")

        partitions = [
            PartitionInfo(
                partition=p.id,
                leader=p.leader if p.leader >= 0 else None,
                replicas=list(p.replicas),
                in_sync_replicas=list(p.isrs),
            )
            for p in sorted(topic.partitions.values(), key=lambda p: p.id)
        ]

        if with_watermarks and partitions:
            marks = await self.watermarks((name, p.partition) for p in partitions)
            for partition in partitions:
                low, high = marks.get((name, partition.partition), (None, None))
                partition.low_watermark = low
                partition.high_watermark = high

        counts = [p.message_count for p in partitions if p.message_count is not None]
        return TopicDetail(
            name=name,
            is_internal=is_internal_topic(name),
            partitions=partitions,
            replication_factor=max((len(p.replicas) for p in partitions), default=0),
            message_count=sum(counts) if counts else None,
        )

    async def topic_configs(self, name: str) -> list[ConfigEntry]:
        await self.require(Capability.DESCRIBE_CONFIGS)
        admin = await self._client()
        resource = ConfigResource(ConfigResource.Type.TOPIC, name)
        futures = await self._run(
            lambda: admin.describe_configs([resource], request_timeout=self.timeout)
        )

        entries: list[ConfigEntry] = []
        for future in futures.values():
            config = future.result(timeout=self.timeout)
            for entry in config.values():
                source = _config_source_name(getattr(entry, "source", None))
                entries.append(
                    ConfigEntry(
                        name=entry.name,
                        value=entry.value,
                        source=source.rsplit(".", 1)[-1],
                        # Anything not inherited from the broker default has
                        # been set deliberately; the UI highlights those.
                        is_default=bool(getattr(entry, "is_default", False))
                        or source == "DEFAULT_CONFIG",
                        is_read_only=bool(getattr(entry, "is_read_only", False)),
                        is_sensitive=bool(getattr(entry, "is_sensitive", False)),
                    )
                )

        entries.sort(key=lambda e: e.name)
        return entries

    # --- consumer groups --------------------------------------------------

    async def list_groups(self) -> list[GroupSummary]:
        await self.require(Capability.LIST_GROUPS)
        admin = await self._client()
        future = await self._run(lambda: admin.list_consumer_groups(request_timeout=self.timeout))
        listing = future.result(timeout=self.timeout)

        summaries = [
            GroupSummary(
                group_id=item.group_id,
                state=_GROUP_STATES.get(
                    str(getattr(item, "state", "")).rsplit(".", 1)[-1].upper(),
                    GroupState.UNKNOWN,
                ),
                is_simple=bool(getattr(item, "is_simple_consumer_group", False)),
            )
            for item in listing.valid
        ]
        summaries.sort(key=lambda g: g.group_id)
        return summaries

    async def describe_group(self, group_id: str, *, with_lag: bool = True) -> GroupDetail:
        await self.require(Capability.DESCRIBE_GROUPS)
        admin = await self._client()
        futures = await self._run(
            lambda: admin.describe_consumer_groups([group_id], request_timeout=self.timeout)
        )
        description = futures[group_id].result(timeout=self.timeout)

        members: list[GroupMember] = []
        assigned: set[tuple[str, int]] = set()
        owner: dict[tuple[str, int], str] = {}

        for member in getattr(description, "members", []):
            grouped: dict[str, list[int]] = {}
            assignment = getattr(member, "assignment", None)
            for tp in getattr(assignment, "topic_partitions", []) or []:
                grouped.setdefault(tp.topic, []).append(tp.partition)
                assigned.add((tp.topic, tp.partition))
                owner[(tp.topic, tp.partition)] = member.member_id

            members.append(
                GroupMember(
                    member_id=member.member_id,
                    client_id=getattr(member, "client_id", None),
                    host=getattr(member, "host", None),
                    group_instance_id=getattr(member, "group_instance_id", None),
                    assignments=[
                        GroupMemberAssignment(topic=topic, partitions=sorted(partitions))
                        for topic, partitions in sorted(grouped.items())
                    ],
                )
            )

        state_name = str(getattr(description, "state", "")).rsplit(".", 1)[-1].upper()
        coordinator = getattr(description, "coordinator", None)

        detail = GroupDetail(
            group_id=group_id,
            state=_GROUP_STATES.get(state_name, GroupState.UNKNOWN),
            is_simple=bool(getattr(description, "is_simple_consumer_group", False)),
            coordinator_id=getattr(coordinator, "id", None),
            partition_assignor=getattr(description, "partition_assignor", None),
            members=members,
        )

        if with_lag:
            detail.lags = await self.group_lag(group_id, owner=owner)
            known = [lag.lag for lag in detail.lags if lag.lag is not None]
            detail.total_lag = sum(known) if known else None

        return detail

    async def group_lag(
        self, group_id: str, *, owner: dict[tuple[str, int], str] | None = None
    ) -> list[PartitionLag]:
        """Committed offsets versus high watermarks.

        No consumer is created. Committed offsets come from the group offsets
        API and the ends of the log from list_offsets.
        """
        await self.require(Capability.LIST_GROUP_OFFSETS)
        admin = await self._client()

        futures = await self._run(
            lambda: admin.list_consumer_group_offsets(
                [ConsumerGroupTopicPartitions(group_id)], request_timeout=self.timeout
            )
        )
        committed = futures[group_id].result(timeout=self.timeout)
        partitions = list(getattr(committed, "topic_partitions", []) or [])
        if not partitions:
            return []

        marks = await self.watermarks((tp.topic, tp.partition) for tp in partitions)

        lags = [
            PartitionLag.build(
                topic=tp.topic,
                partition=tp.partition,
                current_offset=tp.offset if tp.offset is not None and tp.offset >= 0 else None,
                high_watermark=marks.get((tp.topic, tp.partition), (None, None))[1],
                member_id=(owner or {}).get((tp.topic, tp.partition)),
            )
            for tp in partitions
        ]
        lags.sort(key=lambda lag: (lag.topic, lag.partition))
        return lags

    async def groups_for_topic(self, topic: str) -> list[str]:
        """Which groups have committed offsets for a topic.

        Costs one describe per group, so it is only called from a topic detail
        view, never from the topic list.
        """
        try:
            groups = await self.list_groups()
        except KafkaGateError:
            return []

        found: list[str] = []
        for group in groups:
            try:
                lags = await self.group_lag(group.group_id)
            except KafkaGateError:
                continue
            if any(lag.topic == topic for lag in lags):
                found.append(group.group_id)
        return found
