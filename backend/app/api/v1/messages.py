"""Message browsing and search.

Scans are user-initiated and bounded. Nothing here polls, and no message
payload is ever written to disk.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import GatesDep, PrincipalDep, SettingsDep, get_registry, resolve_cluster
from app.clusters.registry import ClusterRegistry
from app.codecs.decode import PayloadFormat
from app.kafka.errors import KafkaGateError
from app.search.dsl import validate_filter
from app.search.scan import (
    MessageScanner,
    ScannedMessage,
    ScanRequest,
    StartFrom,
    StopReason,
    format_counts,
)
from app.security.masking import build_masker

router = APIRouter(prefix="/clusters/{cluster}", tags=["messages"])

ClusterDep = Annotated[str, Depends(resolve_cluster)]
RegistryDep = Annotated[ClusterRegistry, Depends(get_registry)]

# Hard ceilings, so a crafted request cannot ask for an unbounded scan.
MAX_RESULTS_CEILING = 1_000
MAX_SCANNED_CEILING = 500_000
MAX_SECONDS_CEILING = 120.0


class SearchRequest(BaseModel):
    topic: str
    partitions: list[int] | None = Field(default=None, description="All partitions when omitted.")
    start_from: StartFrom = StartFrom.NEWEST
    offset: int | None = None
    timestamp_ms: int | None = None
    filter: str | None = Field(default=None, description="A JMESPath expression.")
    max_results: int = Field(default=100, ge=1, le=MAX_RESULTS_CEILING)
    max_scanned: int = Field(default=50_000, ge=1, le=MAX_SCANNED_CEILING)
    max_seconds: float = Field(default=20.0, gt=0, le=MAX_SECONDS_CEILING)


class PayloadModel(BaseModel):
    format: PayloadFormat
    value: Any = None
    size_bytes: int
    schema_id: int | None = None
    error: str | None = None


class MessageModel(BaseModel):
    topic: str
    partition: int
    offset: int
    timestamp: int | None
    timestamp_type: str | None
    key: PayloadModel
    value: PayloadModel
    headers: dict[str, str]
    masked: bool


class SearchResponse(BaseModel):
    messages: list[MessageModel]
    scanned: int
    elapsed_seconds: float
    stop_reason: StopReason
    partitions_scanned: list[int]
    format_counts: dict[str, int]
    masking_enabled: bool
    filter_error: str | None = None


class FilterValidationRequest(BaseModel):
    filter: str


class FilterValidationResponse(BaseModel):
    valid: bool
    error: str | None = None


def to_model(message: ScannedMessage) -> MessageModel:
    return MessageModel(
        topic=message.topic,
        partition=message.partition,
        offset=message.offset,
        timestamp=message.timestamp,
        timestamp_type=message.timestamp_type,
        key=PayloadModel(
            format=message.key.format,
            value=message.key.value,
            size_bytes=message.key.size_bytes,
            schema_id=message.key.schema_id,
            error=message.key.error,
        ),
        value=PayloadModel(
            format=message.value.format,
            value=message.value.value,
            size_bytes=message.value.size_bytes,
            schema_id=message.value.schema_id,
            error=message.value.error,
        ),
        headers=message.headers,
        masked=message.masked,
    )


@router.post(
    "/messages/search",
    response_model=SearchResponse,
    summary="Scan a topic for messages",
)
async def search_messages(
    cluster: ClusterDep,
    payload: SearchRequest,
    registry: RegistryDep,
    gates: GatesDep,
    settings: SettingsDep,
    _principal: PrincipalDep,
) -> SearchResponse:
    config = registry.get(cluster)

    if payload.filter:
        error = validate_filter(payload.filter)
        if error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    masker = build_masker(
        config.mask_rules,
        cluster_enabled=config.masking_enabled,
        global_enabled=settings.masking_enabled,
    )

    scanner = MessageScanner(config, timeout_seconds=settings.admin_timeout_seconds)
    request = ScanRequest(
        topic=payload.topic,
        partitions=payload.partitions,
        start_from=payload.start_from,
        offset=payload.offset,
        timestamp_ms=payload.timestamp_ms,
        filter_expression=payload.filter,
        max_results=payload.max_results,
        max_scanned=payload.max_scanned,
        max_seconds=payload.max_seconds,
    )

    try:
        # The hard ceiling is the scan's own time budget plus a small margin;
        # a hung broker must not hold the request open indefinitely.
        result = await asyncio.wait_for(
            scanner.scan(request, masker=masker),
            timeout=payload.max_seconds + 15,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="the scan exceeded its time budget",
        ) from exc
    except KafkaGateError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    return SearchResponse(
        messages=[to_model(message) for message in result.messages],
        scanned=result.scanned,
        elapsed_seconds=result.elapsed_seconds,
        stop_reason=result.stop_reason,
        partitions_scanned=result.partitions_scanned,
        format_counts=format_counts(result.messages),
        masking_enabled=masker.enabled,
    )


@router.post(
    "/messages/validate-filter",
    response_model=FilterValidationResponse,
    summary="Check a filter expression without running a scan",
)
async def validate_filter_expression(
    cluster: ClusterDep,
    payload: FilterValidationRequest,
    _principal: PrincipalDep,
) -> FilterValidationResponse:
    error = validate_filter(payload.filter)
    return FilterValidationResponse(valid=error is None, error=error)
