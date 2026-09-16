"""Producing and replaying messages.

Both write real records to a real topic, so both are operator-gated, audited,
and require the destination topic to be typed back as confirmation.

Replay copies messages from one topic to another -- for example to re-process
a time window. It reuses the bounded scanner, so a replay inherits the same
budgets as a search and can never run away.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.deps import GatesDep, PrincipalDep, RegistryDep, SettingsDep, resolve_cluster
from app.api.v1.admin import _client_ip, _guard
from app.kafka.errors import KafkaGateError, translate_kafka_error
from app.kafka.gate import build_client_config
from app.search.scan import MessageScanner, ScanRequest, StartFrom
from app.security.audit import audited
from app.security.masking import Masker
from app.store.models import Role

router = APIRouter(prefix="/clusters/{cluster}", tags=["produce"])

ClusterDep = Annotated[str, Depends(resolve_cluster)]

MAX_REPLAY = 10_000


class ProduceRequest(BaseModel):
    topic: str
    key: str | None = None
    value: str | None = Field(default=None, description="Raw string, or JSON text.")
    headers: dict[str, str] = Field(default_factory=dict)
    partition: int | None = Field(default=None, description="Let Kafka choose when omitted.")
    confirm_topic: str = Field(description="Must equal the destination topic.")


class ProduceResponse(BaseModel):
    topic: str
    partition: int
    offset: int


class ReplayRequest(BaseModel):
    source_topic: str
    target_topic: str
    partitions: list[int] | None = None
    start_from: StartFrom = StartFrom.OLDEST
    offset: int | None = None
    timestamp_ms: int | None = None
    filter: str | None = None
    max_messages: int = Field(default=1000, ge=1, le=MAX_REPLAY)
    max_seconds: float = Field(default=60.0, gt=0, le=300.0)
    preserve_key: bool = True
    dry_run: bool = True
    confirm_target: str | None = None


class ReplayResponse(BaseModel):
    source_topic: str
    target_topic: str
    matched: int
    copied: int
    scanned: int
    elapsed_seconds: float
    stop_reason: str
    applied: bool


@router.post("/produce", response_model=ProduceResponse, summary="Produce a single message")
async def produce_message(
    request: Request,
    cluster: ClusterDep,
    payload: ProduceRequest,
    principal: PrincipalDep,
    registry: RegistryDep,
    settings: SettingsDep,
    gates: GatesDep,
) -> ProduceResponse:
    _guard(
        request,
        cluster,
        principal,
        registry,
        settings,
        required=Role.OPERATOR,
        action="message.produce",
        target=payload.topic,
    )

    if payload.confirm_topic != payload.topic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"type the destination topic {payload.topic!r} exactly to confirm",
        )

    config = registry.get(cluster)
    gate = await gates.get(cluster)

    def send() -> tuple[int, int]:
        from confluent_kafka import Producer

        producer = Producer(build_client_config(config, settings.admin_timeout_seconds))
        result: dict[str, Any] = {}

        def on_delivery(error: Any, message: Any) -> None:
            if error is not None:
                result["error"] = error
            else:
                result["partition"] = message.partition()
                result["offset"] = message.offset()

        producer.produce(
            payload.topic,
            key=payload.key.encode() if payload.key is not None else None,
            value=payload.value.encode() if payload.value is not None else None,
            headers=[(name, value.encode()) for name, value in payload.headers.items()],
            partition=payload.partition if payload.partition is not None else -1,
            on_delivery=on_delivery,
        )
        # flush() returns the number still queued; anything left means the
        # broker never acknowledged.
        remaining = producer.flush(settings.admin_timeout_seconds)
        if remaining:
            raise KafkaGateError("the broker did not acknowledge the message in time")
        if "error" in result:
            raise translate_kafka_error(Exception(result["error"]))
        return int(result.get("partition", -1)), int(result.get("offset", -1))

    with audited(
        request.app.state.engine,
        principal=principal,
        action="message.produce",
        cluster=cluster,
        target=payload.topic,
        source_ip=_client_ip(request),
    ) as context:
        try:
            partition, offset = await gate._run(send)
        except KafkaGateError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message
            ) from exc
        # The payload itself is deliberately not recorded -- only where it
        # landed and how big it was.
        context["after"] = {
            "partition": partition,
            "offset": offset,
            "value_bytes": len(payload.value or ""),
            "has_key": payload.key is not None,
        }

    return ProduceResponse(topic=payload.topic, partition=partition, offset=offset)


@router.post("/replay", response_model=ReplayResponse, summary="Copy messages between topics")
async def replay_messages(
    request: Request,
    cluster: ClusterDep,
    payload: ReplayRequest,
    principal: PrincipalDep,
    registry: RegistryDep,
    settings: SettingsDep,
    gates: GatesDep,
) -> ReplayResponse:
    if payload.source_topic == payload.target_topic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source and target must differ; replaying a topic into itself would loop",
        )

    config = registry.get(cluster)
    gate = await gates.get(cluster)
    scanner = MessageScanner(config, timeout_seconds=settings.admin_timeout_seconds)

    # The scan runs for both dry-run and execution, so the preview count is
    # the real count rather than an estimate.
    scan_request = ScanRequest(
        topic=payload.source_topic,
        partitions=payload.partitions,
        start_from=payload.start_from,
        offset=payload.offset,
        timestamp_ms=payload.timestamp_ms,
        filter_expression=payload.filter,
        max_results=payload.max_messages,
        max_scanned=MAX_REPLAY * 10,
        max_seconds=payload.max_seconds,
    )

    try:
        # Replay must copy the true bytes, so masking is off for this read.
        # Nothing is returned to the browser.
        result = await scanner.scan(scan_request, masker=Masker([], enabled=False))
    except KafkaGateError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    if payload.dry_run:
        return ReplayResponse(
            source_topic=payload.source_topic,
            target_topic=payload.target_topic,
            matched=len(result.messages),
            copied=0,
            scanned=result.scanned,
            elapsed_seconds=result.elapsed_seconds,
            stop_reason=str(result.stop_reason),
            applied=False,
        )

    _guard(
        request,
        cluster,
        principal,
        registry,
        settings,
        required=Role.OPERATOR,
        action="message.replay",
        target=payload.target_topic,
    )

    if payload.confirm_target != payload.target_topic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"type the target topic {payload.target_topic!r} exactly to confirm",
        )

    def copy() -> int:
        from confluent_kafka import Producer

        producer = Producer(build_client_config(config, settings.admin_timeout_seconds))
        sent = 0
        for message in result.messages:
            raw_key = None
            if payload.preserve_key and message.key.value is not None:
                raw_key = (
                    message.key.value
                    if isinstance(message.key.value, str)
                    else json.dumps(message.key.value)
                ).encode()
            raw_value = (
                message.value.value
                if isinstance(message.value.value, str)
                else json.dumps(message.value.value)
            ).encode()

            producer.produce(
                payload.target_topic,
                key=raw_key,
                value=raw_value,
                headers=[(name, value.encode()) for name, value in message.headers.items()],
            )
            sent += 1
            producer.poll(0)

        remaining = producer.flush(max(30.0, payload.max_seconds))
        if remaining:
            raise KafkaGateError(f"{remaining} message(s) were not acknowledged by the broker")
        return sent

    with audited(
        request.app.state.engine,
        principal=principal,
        action="message.replay",
        cluster=cluster,
        target=payload.target_topic,
        before={"source": payload.source_topic, "filter": payload.filter},
        source_ip=_client_ip(request),
    ) as context:
        try:
            copied = await gate._run(copy)
        except KafkaGateError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message
            ) from exc
        context["after"] = {"copied": copied}

    gates.invalidate(cluster)
    return ReplayResponse(
        source_topic=payload.source_topic,
        target_topic=payload.target_topic,
        matched=len(result.messages),
        copied=copied,
        scanned=result.scanned,
        elapsed_seconds=result.elapsed_seconds,
        stop_reason=str(result.stop_reason),
        applied=True,
    )
