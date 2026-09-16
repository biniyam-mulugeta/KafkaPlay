"""Consumer groups and lag.

Lag is computed from committed offsets and log-end offsets via the
AdminClient. No consumer is ever created to measure it -- that would add group
churn and broker load for information the offsets API already provides.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import GatesDep, PrincipalDep, resolve_cluster
from app.kafka.gates import cached, degradable
from app.kafka.models import GroupDetail, GroupListResponse, PartitionLag

router = APIRouter(prefix="/clusters/{cluster}/consumer-groups", tags=["consumer-groups"])

ClusterDep = Annotated[str, Depends(resolve_cluster)]


@router.get("", response_model=GroupListResponse, summary="List consumer groups")
async def list_groups(
    cluster: ClusterDep,
    gates: GatesDep,
    _principal: PrincipalDep,
    with_lag: Annotated[
        bool,
        Query(description="Also compute total lag per group. Costs one call per group."),
    ] = False,
) -> GroupListResponse:
    gate = await gates.get(cluster)

    async def load() -> GroupListResponse:
        groups = await gate.list_groups()
        if with_lag:
            for group in groups:
                try:
                    lags = await gate.group_lag(group.group_id)
                except Exception:
                    # One unreadable group must not blank the whole list.
                    continue
                known = [lag.lag for lag in lags if lag.lag is not None]
                group.total_lag = sum(known) if known else None
                group.topics = sorted({lag.topic for lag in lags})
        return GroupListResponse(groups=groups)

    result, degraded = await degradable(
        lambda: cached(gates, cluster, f"groups:{with_lag}", load),
        fallback=GroupListResponse(),
        context=f"list_groups:{cluster}",
    )
    result.degraded = degraded
    return result


@router.get("/{group_id}", response_model=GroupDetail, summary="Consumer group detail")
async def get_group(
    cluster: ClusterDep,
    group_id: str,
    gates: GatesDep,
    _principal: PrincipalDep,
) -> GroupDetail:
    gate = await gates.get(cluster)

    async def load() -> GroupDetail:
        return await gate.describe_group(group_id)

    result, degraded = await degradable(
        lambda: cached(gates, cluster, f"group:{group_id}", load),
        fallback=GroupDetail(group_id=group_id),
        context=f"describe_group:{cluster}/{group_id}",
    )
    result.degraded = degraded
    return result


@router.get("/{group_id}/lag", response_model=list[PartitionLag], summary="Lag per partition")
async def get_group_lag(
    cluster: ClusterDep,
    group_id: str,
    gates: GatesDep,
    _principal: PrincipalDep,
) -> list[PartitionLag]:
    gate = await gates.get(cluster)

    async def load() -> list[PartitionLag]:
        return await gate.group_lag(group_id)

    empty: list[PartitionLag] = []
    result, _ = await degradable(
        lambda: cached(gates, cluster, f"group-lag:{group_id}", load),
        fallback=empty,
        context=f"group_lag:{cluster}/{group_id}",
    )
    return result
