"""Topic listing and detail.

Deliberately tiered by cost:

  list          one metadata call, cached
  detail        metadata plus batched watermarks
  configs       one describe_configs
  groups        expensive, so it is a separate endpoint the UI fetches lazily
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import GatesDep, PrincipalDep, resolve_cluster
from app.kafka.gates import cached, degradable
from app.kafka.models import (
    TopicConfigResponse,
    TopicDetail,
    TopicListResponse,
)

router = APIRouter(prefix="/clusters/{cluster}/topics", tags=["topics"])

ClusterDep = Annotated[str, Depends(resolve_cluster)]


@router.get("", response_model=TopicListResponse, summary="List topics")
async def list_topics(
    cluster: ClusterDep,
    gates: GatesDep,
    _principal: PrincipalDep,
    include_internal: Annotated[bool, Query(description="Include __consumer_offsets etc.")] = False,
) -> TopicListResponse:
    gate = await gates.get(cluster)

    async def load() -> TopicListResponse:
        topics = await gate.list_topics(include_internal=include_internal)
        return TopicListResponse(topics=topics)

    result, degraded = await degradable(
        lambda: cached(gates, cluster, f"topics:{include_internal}", load),
        fallback=TopicListResponse(),
        context=f"list_topics:{cluster}",
    )
    result.degraded = degraded
    return result


@router.get("/{topic}", response_model=TopicDetail, summary="Topic detail")
async def get_topic(
    cluster: ClusterDep,
    topic: str,
    gates: GatesDep,
    _principal: PrincipalDep,
) -> TopicDetail:
    gate = await gates.get(cluster)

    async def load() -> TopicDetail:
        return await gate.describe_topic(topic)

    try:
        result, degraded = await degradable(
            lambda: cached(gates, cluster, f"topic:{topic}", load),
            fallback=TopicDetail(name=topic),
            context=f"describe_topic:{cluster}/{topic}",
        )
    except Exception as exc:  # unknown topic is a 404, not a degraded state
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if degraded and not result.partitions:
        result.degraded = degraded
    return result


@router.get("/{topic}/configs", response_model=TopicConfigResponse, summary="Topic configuration")
async def get_topic_configs(
    cluster: ClusterDep,
    topic: str,
    gates: GatesDep,
    _principal: PrincipalDep,
) -> TopicConfigResponse:
    gate = await gates.get(cluster)

    async def load() -> TopicConfigResponse:
        return TopicConfigResponse(topic=topic, configs=await gate.topic_configs(topic))

    result, degraded = await degradable(
        lambda: cached(gates, cluster, f"topic-configs:{topic}", load),
        fallback=TopicConfigResponse(topic=topic),
        context=f"topic_configs:{cluster}/{topic}",
    )
    result.degraded = degraded
    return result


@router.get(
    "/{topic}/consumer-groups",
    response_model=list[str],
    summary="Consumer groups reading this topic",
)
async def get_topic_groups(
    cluster: ClusterDep,
    topic: str,
    gates: GatesDep,
    _principal: PrincipalDep,
) -> list[str]:
    gate = await gates.get(cluster)

    async def load() -> list[str]:
        return await gate.groups_for_topic(topic)

    empty: list[str] = []
    result, _ = await degradable(
        lambda: cached(gates, cluster, f"topic-groups:{topic}", load),
        fallback=empty,
        context=f"topic_groups:{cluster}/{topic}",
    )
    return result
