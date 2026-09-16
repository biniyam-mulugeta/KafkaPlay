"""Mutating endpoints: topics, configs, offsets, produce.

Every route here passes through the same three gates, in this order:

1. read-only  -- the deployment or cluster forbids writes at all
2. role       -- operator for data actions, admin for structural ones
3. audit      -- the attempt is recorded whatever the outcome

Destructive operations additionally require a preview to have been fetched
and the exact target to be confirmed in the request body.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.deps import GatesDep, PrincipalDep, RegistryDep, SettingsDep, resolve_cluster
from app.auth.rbac import AuthorizationError, Principal, ReadOnlyError, require_writable
from app.kafka.admin_ops import KafkaAdminOps, ResetPreview, ResetTo
from app.kafka.errors import KafkaGateError
from app.security.audit import audited, record_denial
from app.store.models import Role

router = APIRouter(prefix="/clusters/{cluster}", tags=["admin"])

ClusterDep = Annotated[str, Depends(resolve_cluster)]

# Names that would let a caller break a topic in ways that are hard to undo.
PROTECTED_CONFIGS = frozenset({"cleanup.policy"})


def _guard(
    request: Request,
    cluster: str,
    principal: Principal,
    registry: RegistryDep,
    settings: SettingsDep,
    *,
    required: Role,
    action: str,
    target: str | None = None,
) -> None:
    """Apply read-only and role checks, auditing a refusal."""
    config = registry.get(cluster)
    try:
        require_writable(
            principal,
            required,
            cluster=cluster,
            global_read_only=settings.read_only,
            cluster_read_only=config.read_only,
        )
    except (ReadOnlyError, AuthorizationError) as exc:
        record_denial(
            request.app.state.engine,
            principal=principal,
            action=action,
            reason=exc.message,
            cluster=cluster,
            target=target,
            source_ip=request.client.host if request.client else None,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message) from exc


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# --- topics ---------------------------------------------------------------


class CreateTopicRequest(BaseModel):
    name: str = Field(min_length=1, max_length=249, pattern=r"^[a-zA-Z0-9._-]+$")
    partitions: int = Field(ge=1, le=10_000)
    replication_factor: int = Field(ge=1, le=10)
    configs: dict[str, str] = Field(default_factory=dict)


class DeleteTopicRequest(BaseModel):
    confirm_name: str = Field(description="Must equal the topic name, typed by the operator.")


class AddPartitionsRequest(BaseModel):
    total_partitions: int = Field(ge=1, le=10_000)


class AlterConfigsRequest(BaseModel):
    updates: dict[str, str]
    dry_run: bool = True


class ConfigChangeModel(BaseModel):
    name: str
    current_value: str | None
    new_value: str | None
    is_default: bool


class ConfigDiffResponse(BaseModel):
    topic: str
    changes: list[ConfigChangeModel]
    applied: bool


@router.post("/topics", status_code=status.HTTP_201_CREATED, summary="Create a topic")
async def create_topic(
    request: Request,
    cluster: ClusterDep,
    payload: CreateTopicRequest,
    principal: PrincipalDep,
    registry: RegistryDep,
    settings: SettingsDep,
    gates: GatesDep,
) -> dict[str, str]:
    _guard(
        request,
        cluster,
        principal,
        registry,
        settings,
        required=Role.ADMIN,
        action="topic.create",
        target=payload.name,
    )
    gate = await gates.get(cluster)
    ops = KafkaAdminOps(gate)

    with audited(
        request.app.state.engine,
        principal=principal,
        action="topic.create",
        cluster=cluster,
        target=payload.name,
        source_ip=_client_ip(request),
    ) as context:
        try:
            await ops.create_topic(
                payload.name,
                partitions=payload.partitions,
                replication_factor=payload.replication_factor,
                configs=payload.configs,
            )
        except KafkaGateError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message
            ) from exc
        context["after"] = {
            "partitions": payload.partitions,
            "replication_factor": payload.replication_factor,
            "configs": payload.configs,
        }

    gates.invalidate(cluster)
    return {"status": "created", "topic": payload.name}


@router.delete("/topics/{topic}", summary="Delete a topic")
async def delete_topic(
    request: Request,
    cluster: ClusterDep,
    topic: str,
    payload: DeleteTopicRequest,
    principal: PrincipalDep,
    registry: RegistryDep,
    settings: SettingsDep,
    gates: GatesDep,
) -> dict[str, str]:
    _guard(
        request,
        cluster,
        principal,
        registry,
        settings,
        required=Role.ADMIN,
        action="topic.delete",
        target=topic,
    )

    # Typed confirmation: deleting a topic is unrecoverable.
    if payload.confirm_name != topic:
        record_denial(
            request.app.state.engine,
            principal=principal,
            action="topic.delete",
            reason="confirmation did not match the topic name",
            cluster=cluster,
            target=topic,
            source_ip=_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"type the topic name {topic!r} exactly to confirm deletion",
        )

    gate = await gates.get(cluster)
    ops = KafkaAdminOps(gate)

    before: dict[str, Any] = {}
    try:
        detail = await gate.describe_topic(topic, with_watermarks=True)
        before = {
            "partitions": len(detail.partitions),
            "replication_factor": detail.replication_factor,
            "approx_messages": detail.message_count,
        }
    except KafkaGateError:
        before = {}

    with audited(
        request.app.state.engine,
        principal=principal,
        action="topic.delete",
        cluster=cluster,
        target=topic,
        before=before,
        source_ip=_client_ip(request),
    ):
        try:
            await ops.delete_topic(topic)
        except KafkaGateError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message
            ) from exc

    gates.invalidate(cluster)
    return {"status": "deleted", "topic": topic}


@router.post("/topics/{topic}/partitions", summary="Increase a topic's partition count")
async def add_partitions(
    request: Request,
    cluster: ClusterDep,
    topic: str,
    payload: AddPartitionsRequest,
    principal: PrincipalDep,
    registry: RegistryDep,
    settings: SettingsDep,
    gates: GatesDep,
) -> dict[str, Any]:
    _guard(
        request,
        cluster,
        principal,
        registry,
        settings,
        required=Role.ADMIN,
        action="topic.add_partitions",
        target=topic,
    )
    gate = await gates.get(cluster)
    detail = await gate.describe_topic(topic, with_watermarks=False)
    current = len(detail.partitions)

    if payload.total_partitions <= current:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"topic {topic!r} already has {current} partitions; Kafka cannot reduce "
                "the partition count, only increase it"
            ),
        )

    with audited(
        request.app.state.engine,
        principal=principal,
        action="topic.add_partitions",
        cluster=cluster,
        target=topic,
        before={"partitions": current},
        source_ip=_client_ip(request),
    ) as context:
        try:
            await KafkaAdminOps(gate).add_partitions(topic, total=payload.total_partitions)
        except KafkaGateError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message
            ) from exc
        context["after"] = {"partitions": payload.total_partitions}
        context["detail"] = "key-to-partition mapping changes for records produced after this point"

    gates.invalidate(cluster)
    return {
        "status": "updated",
        "topic": topic,
        "partitions": payload.total_partitions,
        "warning": (
            "Existing records keep their partition. New records with the same key may "
            "land on a different partition, so per-key ordering is not preserved across "
            "this change."
        ),
    }


@router.post(
    "/topics/{topic}/configs",
    response_model=ConfigDiffResponse,
    summary="Preview or apply topic configuration changes",
)
async def alter_configs(
    request: Request,
    cluster: ClusterDep,
    topic: str,
    payload: AlterConfigsRequest,
    principal: PrincipalDep,
    registry: RegistryDep,
    settings: SettingsDep,
    gates: GatesDep,
) -> ConfigDiffResponse:
    gate = await gates.get(cluster)
    ops = KafkaAdminOps(gate)

    # A dry run is a read: it needs neither the write gate nor an audit row.
    changes = await ops.preview_config_change(topic, payload.updates)
    models = [
        ConfigChangeModel(
            name=change.name,
            current_value=change.current_value,
            new_value=change.new_value,
            is_default=change.is_default,
        )
        for change in changes
    ]

    if payload.dry_run:
        return ConfigDiffResponse(topic=topic, changes=models, applied=False)

    _guard(
        request,
        cluster,
        principal,
        registry,
        settings,
        required=Role.ADMIN,
        action="topic.alter_configs",
        target=topic,
    )

    risky = sorted(set(payload.updates) & PROTECTED_CONFIGS)
    with audited(
        request.app.state.engine,
        principal=principal,
        action="topic.alter_configs",
        cluster=cluster,
        target=topic,
        before={change.name: change.current_value for change in changes},
        source_ip=_client_ip(request),
    ) as context:
        try:
            await ops.alter_topic_configs(topic, payload.updates)
        except KafkaGateError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message
            ) from exc
        context["after"] = payload.updates
        if risky:
            context["detail"] = f"changed protected settings: {', '.join(risky)}"

    gates.invalidate(cluster)
    return ConfigDiffResponse(topic=topic, changes=models, applied=True)


# --- consumer group offsets ------------------------------------------------


class OffsetResetRequest(BaseModel):
    reset_to: ResetTo
    topics: list[str] | None = None
    target_offset: int | None = None
    timestamp_ms: int | None = None
    shift_by: int | None = None
    dry_run: bool = True
    confirm_group_id: str | None = Field(
        default=None,
        description="Must equal the group id when dry_run is false.",
    )


class OffsetChangeModel(BaseModel):
    topic: str
    partition: int
    current_offset: int | None
    target_offset: int
    low_watermark: int | None
    high_watermark: int | None
    messages_skipped: int
    messages_replayed: int


class OffsetResetResponse(BaseModel):
    group_id: str
    reset_to: ResetTo
    changes: list[OffsetChangeModel]
    total_skipped: int
    total_replayed: int
    group_state: str
    member_count: int
    is_safe: bool
    applied: bool
    blocked_reason: str | None = None


def _to_response(preview: ResetPreview, *, applied: bool) -> OffsetResetResponse:
    return OffsetResetResponse(
        group_id=preview.group_id,
        reset_to=preview.reset_to,
        changes=[
            OffsetChangeModel(
                topic=change.topic,
                partition=change.partition,
                current_offset=change.current_offset,
                target_offset=change.target_offset,
                low_watermark=change.low_watermark,
                high_watermark=change.high_watermark,
                messages_skipped=change.messages_skipped,
                messages_replayed=change.messages_replayed,
            )
            for change in preview.changes
        ],
        total_skipped=preview.total_skipped,
        total_replayed=preview.total_replayed,
        group_state=str(preview.group_state),
        member_count=preview.member_count,
        is_safe=preview.is_safe,
        applied=applied,
        blocked_reason=(
            None
            if preview.is_safe
            else (
                f"the group has {preview.member_count} active member(s). "
                "Stop its consumers first: resetting offsets under a running consumer "
                "silently skips or replays records."
            )
        ),
    )


@router.post(
    "/consumer-groups/{group_id}/offsets:reset",
    response_model=OffsetResetResponse,
    summary="Preview or apply a consumer group offset reset",
)
async def reset_offsets(
    request: Request,
    cluster: ClusterDep,
    group_id: str,
    payload: OffsetResetRequest,
    principal: PrincipalDep,
    registry: RegistryDep,
    settings: SettingsDep,
    gates: GatesDep,
) -> OffsetResetResponse:
    gate = await gates.get(cluster)
    ops = KafkaAdminOps(gate)

    try:
        preview = await ops.preview_offset_reset(
            group_id,
            reset_to=payload.reset_to,
            topics=payload.topics,
            target_offset=payload.target_offset,
            timestamp_ms=payload.timestamp_ms,
            shift_by=payload.shift_by,
        )
    except KafkaGateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message) from exc

    if payload.dry_run:
        return _to_response(preview, applied=False)

    _guard(
        request,
        cluster,
        principal,
        registry,
        settings,
        required=Role.OPERATOR,
        action="group.offsets.reset",
        target=group_id,
    )

    if payload.confirm_group_id != group_id:
        record_denial(
            request.app.state.engine,
            principal=principal,
            action="group.offsets.reset",
            reason="confirmation did not match the group id",
            cluster=cluster,
            target=group_id,
            source_ip=_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"type the group id {group_id!r} exactly to confirm the reset",
        )

    if not preview.is_safe:
        reason = f"group is active with {preview.member_count} member(s)"
        record_denial(
            request.app.state.engine,
            principal=principal,
            action="group.offsets.reset",
            reason=reason,
            cluster=cluster,
            target=group_id,
            source_ip=_client_ip(request),
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)

    with audited(
        request.app.state.engine,
        principal=principal,
        action="group.offsets.reset",
        cluster=cluster,
        target=group_id,
        before={
            f"{change.topic}:{change.partition}": change.current_offset
            for change in preview.changes
        },
        source_ip=_client_ip(request),
    ) as context:
        try:
            await ops.apply_offset_reset(preview)
        except KafkaGateError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
        context["after"] = {
            f"{change.topic}:{change.partition}": change.target_offset for change in preview.changes
        }
        context["detail"] = (
            f"reset_to={payload.reset_to} "
            f"skipped={preview.total_skipped} replayed={preview.total_replayed}"
        )

    gates.invalidate(cluster)
    return _to_response(preview, applied=True)


@router.delete("/consumer-groups/{group_id}", summary="Delete a consumer group")
async def delete_group(
    request: Request,
    cluster: ClusterDep,
    group_id: str,
    principal: PrincipalDep,
    registry: RegistryDep,
    settings: SettingsDep,
    gates: GatesDep,
) -> dict[str, str]:
    _guard(
        request,
        cluster,
        principal,
        registry,
        settings,
        required=Role.ADMIN,
        action="group.delete",
        target=group_id,
    )
    gate = await gates.get(cluster)

    with audited(
        request.app.state.engine,
        principal=principal,
        action="group.delete",
        cluster=cluster,
        target=group_id,
        source_ip=_client_ip(request),
    ):
        try:
            await KafkaAdminOps(gate).delete_group(group_id)
        except KafkaGateError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc

    gates.invalidate(cluster)
    return {"status": "deleted", "group_id": group_id}


@router.post("/elect-leaders", summary="Run a preferred-leader election")
async def elect_leaders(
    request: Request,
    cluster: ClusterDep,
    principal: PrincipalDep,
    registry: RegistryDep,
    settings: SettingsDep,
    gates: GatesDep,
) -> dict[str, Any]:
    _guard(
        request,
        cluster,
        principal,
        registry,
        settings,
        required=Role.OPERATOR,
        action="cluster.elect_leaders",
    )
    gate = await gates.get(cluster)

    with audited(
        request.app.state.engine,
        principal=principal,
        action="cluster.elect_leaders",
        cluster=cluster,
        source_ip=_client_ip(request),
    ) as context:
        try:
            count = await KafkaAdminOps(gate).elect_preferred_leaders()
        except KafkaGateError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message
            ) from exc
        context["detail"] = "preferred-leader election for all partitions"

    gates.invalidate(cluster)
    return {"status": "requested", "partitions": count}
