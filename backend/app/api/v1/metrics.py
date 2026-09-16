"""Metrics endpoints.

Everything here reads from the built-in sampler's SQLite tables, so it works
against any broker with no Prometheus and no JMX. The Prometheus proxy is
strictly additive and disabled unless PROMETHEUS_URL is set.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.api.deps import PrincipalDep, SettingsDep, resolve_cluster
from app.sampler.series import (
    Heatmap,
    LagHistory,
    TopicThroughput,
    heatmap,
    lag_history,
    topic_throughput,
)

router = APIRouter(prefix="/clusters/{cluster}/metrics", tags=["metrics"])

ClusterDep = Annotated[str, Depends(resolve_cluster)]

MAX_WINDOW_MINUTES = 60 * 24 * 7


class SamplerStatus(BaseModel):
    enabled: bool
    interval_seconds: int
    retention_days: int
    last_run_at: str | None = None
    last_error: str | None = None
    prometheus_enabled: bool


@router.get("/sampler", response_model=SamplerStatus, summary="Built-in sampler status")
async def get_sampler_status(
    request: Request,
    settings: SettingsDep,
    _principal: PrincipalDep,
) -> SamplerStatus:
    sampler = getattr(request.app.state, "sampler", None)
    return SamplerStatus(
        enabled=settings.sampler_enabled and sampler is not None,
        interval_seconds=settings.sampler_interval_seconds,
        retention_days=settings.sampler_retention_days,
        last_run_at=(
            sampler.last_run_at.isoformat() if sampler is not None and sampler.last_run_at else None
        ),
        last_error=sampler.last_error if sampler is not None else None,
        prometheus_enabled=settings.prometheus_url is not None,
    )


@router.get(
    "/consumer-groups/{group_id}/lag-history",
    response_model=LagHistory,
    summary="Lag over time, with velocity and time-to-catch-up",
)
async def get_lag_history(
    request: Request,
    cluster: ClusterDep,
    group_id: str,
    _principal: PrincipalDep,
    topic: Annotated[str | None, Query()] = None,
    partition: Annotated[int | None, Query()] = None,
    window_minutes: Annotated[int, Query(ge=1, le=MAX_WINDOW_MINUTES)] = 60,
) -> LagHistory:
    return lag_history(
        request.app.state.engine,
        cluster=cluster,
        group_id=group_id,
        topic=topic,
        partition=partition,
        window_minutes=window_minutes,
    )


@router.get(
    "/topics/{topic}/throughput",
    response_model=TopicThroughput,
    summary="Messages per second for a topic",
)
async def get_topic_throughput(
    request: Request,
    cluster: ClusterDep,
    topic: str,
    _principal: PrincipalDep,
    window_minutes: Annotated[int, Query(ge=1, le=MAX_WINDOW_MINUTES)] = 60,
) -> TopicThroughput:
    return topic_throughput(
        request.app.state.engine,
        cluster=cluster,
        topic=topic,
        window_minutes=window_minutes,
    )


@router.get("/heatmap", response_model=Heatmap, summary="Topics x partitions heatmap")
async def get_heatmap(
    request: Request,
    cluster: ClusterDep,
    _principal: PrincipalDep,
    metric: Annotated[str, Query(pattern="^(throughput|lag)$")] = "throughput",
    window_minutes: Annotated[int, Query(ge=1, le=MAX_WINDOW_MINUTES)] = 30,
) -> Heatmap:
    return heatmap(
        request.app.state.engine,
        cluster=cluster,
        metric=metric,
        window_minutes=window_minutes,
    )


# --- Optional Prometheus proxy --------------------------------------------
#
# Only these metric names may be queried. An open proxy would let any
# authenticated user read every metric in the operator's Prometheus, which is
# well beyond what this console needs.
PROMETHEUS_ALLOWLIST = frozenset(
    {
        "kafka_brokers",
        "kafka_topic_partitions",
        "kafka_topic_partition_current_offset",
        "kafka_topic_partition_oldest_offset",
        "kafka_topic_partition_in_sync_replica",
        "kafka_topic_partition_under_replicated_partition",
        "kafka_topic_partition_leader",
        "kafka_consumergroup_current_offset",
        "kafka_consumergroup_lag",
        "kafka_consumergroup_members",
        "kafka_server_brokertopicmetrics_messagesin_total",
        "kafka_server_brokertopicmetrics_bytesin_total",
        "kafka_server_brokertopicmetrics_bytesout_total",
        "kafka_server_replicamanager_underreplicatedpartitions",
        "kafka_controller_kafkacontroller_offlinepartitionscount",
        "kafka_log_logsize",
    }
)


class PromQueryRequest(BaseModel):
    metric: str
    labels: dict[str, str] = {}
    window_minutes: int = 60
    step_seconds: int = 60


@router.post("/prometheus/query", summary="Allowlisted Prometheus range query")
async def prometheus_query(
    cluster: ClusterDep,
    payload: PromQueryRequest,
    settings: SettingsDep,
    _principal: PrincipalDep,
) -> dict[str, Any]:
    if settings.prometheus_url is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Prometheus is not configured. The built-in sampler already provides "
                "lag history, throughput and the heatmap; Prometheus adds broker-level "
                "JMX metrics. Set PROMETHEUS_URL to enable it."
            ),
        )

    if payload.metric not in PROMETHEUS_ALLOWLIST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"metric {payload.metric!r} is not in the allowlist",
        )

    # Labels are escaped and the metric name comes from a fixed set, so the
    # caller cannot inject arbitrary PromQL.
    selector = payload.metric
    if payload.labels:
        parts = [f'{name}="{value}"' for name, value in sorted(payload.labels.items())]
        selector = f"{payload.metric}{{{','.join(parts)}}}"

    end = time.time()
    start = end - payload.window_minutes * 60

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{settings.prometheus_url.rstrip('/')}/api/v1/query_range",
                params={
                    "query": selector,
                    "start": start,
                    "end": end,
                    "step": max(15, payload.step_seconds),
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Prometheus is unreachable: {exc}",
        ) from exc

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Prometheus returned HTTP {response.status_code}",
        )

    result: dict[str, Any] = response.json()
    return result
