"""Cluster overview and replication health."""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import GatesDep, PrincipalDep, SettingsDep, resolve_cluster
from app.kafka.gates import cached, degradable
from app.kafka.models import (
    BrokerLoad,
    Capability,
    ClusterInfo,
    ReplicaCell,
    ReplicationResponse,
)

router = APIRouter(prefix="/clusters/{cluster}", tags=["cluster"])

ClusterDep = Annotated[str, Depends(resolve_cluster)]

MIN_ISR_CONFIG = "min.insync.replicas"


@router.get("/overview", response_model=ClusterInfo, summary="Cluster overview")
async def get_overview(
    cluster: ClusterDep,
    gates: GatesDep,
    settings: SettingsDep,
    _principal: PrincipalDep,
) -> ClusterInfo:
    gate = await gates.get(cluster)

    async def load() -> ClusterInfo:
        return await gate.describe_cluster()

    fallback = ClusterInfo(name=cluster, label=gate.cluster.display_name)
    result, degraded = await degradable(
        lambda: cached(gates, cluster, "overview", load),
        fallback=fallback,
        context=f"overview:{cluster}",
    )
    result.degraded = degraded
    # Global read-only wins over the per-cluster setting.
    result.read_only = result.read_only or settings.read_only
    return result


@router.get("/replication", response_model=ReplicationResponse, summary="Replication health")
async def get_replication(
    cluster: ClusterDep,
    gates: GatesDep,
    _principal: PrincipalDep,
) -> ReplicationResponse:
    """Replica placement across brokers.

    Built entirely from metadata and describe_configs, so it works without JMX
    and therefore on managed clusters too.
    """
    gate = await gates.get(cluster)

    async def load() -> ReplicationResponse:
        topics = await gate.list_topics(include_internal=False)

        cells: list[ReplicaCell] = []
        leaders: dict[int, int] = defaultdict(int)
        replicas_per_broker: dict[int, int] = defaultdict(int)
        non_preferred = 0

        capabilities = await gate.capabilities()
        can_read_configs = Capability.DESCRIBE_CONFIGS in capabilities

        for summary in topics:
            detail = await gate.describe_topic(summary.name, with_watermarks=False)

            min_isr: int | None = None
            if can_read_configs:
                try:
                    configs = await gate.topic_configs(summary.name)
                    entry = next((c for c in configs if c.name == MIN_ISR_CONFIG), None)
                    if entry and entry.value is not None:
                        min_isr = int(entry.value)
                except Exception:
                    min_isr = None

            for partition in detail.partitions:
                if partition.leader is not None:
                    leaders[partition.leader] += 1
                for replica in partition.replicas:
                    replicas_per_broker[replica] += 1

                # The preferred leader is the first replica; anything else
                # means a past failover that a leader election would undo.
                if (
                    partition.leader is not None
                    and partition.replicas
                    and partition.leader != partition.replicas[0]
                ):
                    non_preferred += 1

                in_sync = len(partition.in_sync_replicas)
                cells.append(
                    ReplicaCell(
                        topic=summary.name,
                        partition=partition.partition,
                        leader=partition.leader,
                        replicas=partition.replicas,
                        in_sync_replicas=partition.in_sync_replicas,
                        is_under_replicated=partition.is_under_replicated,
                        is_offline=partition.is_offline,
                        min_insync_replicas=min_isr,
                        # Only a warning when replication headroom is being
                        # consumed. On an RF=1 topic, ISR==min.insync.replicas
                        # is the designed steady state, not a degradation.
                        at_min_isr=(
                            min_isr is not None
                            and in_sync <= min_isr
                            and len(partition.replicas) > min_isr
                        ),
                    )
                )

        broker_ids = sorted(set(leaders) | set(replicas_per_broker))
        return ReplicationResponse(
            cells=cells,
            broker_load=[
                BrokerLoad(
                    broker_id=broker_id,
                    leader_count=leaders.get(broker_id, 0),
                    replica_count=replicas_per_broker.get(broker_id, 0),
                )
                for broker_id in broker_ids
            ],
            under_replicated_count=sum(1 for c in cells if c.is_under_replicated),
            offline_count=sum(1 for c in cells if c.is_offline),
            at_min_isr_count=sum(1 for c in cells if c.at_min_isr),
            non_preferred_leader_count=non_preferred,
        )

    result, degraded = await degradable(
        lambda: cached(gates, cluster, "replication", load),
        fallback=ReplicationResponse(),
        context=f"replication:{cluster}",
    )
    result.degraded = degraded
    return result
