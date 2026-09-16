"""Schema Registry browser and ACL management."""

from __future__ import annotations

import difflib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.api.deps import GatesDep, PrincipalDep, RegistryDep, SettingsDep, resolve_cluster
from app.api.v1.admin import _client_ip, _guard
from app.kafka.acls import (
    AclListResponse,
    AclOps,
    AclPattern,
    AclResourceType,
    available_operations,
    available_permissions,
)
from app.kafka.errors import KafkaGateError
from app.schemas.registry import (
    SchemaRegistryClient,
    SchemaRegistryError,
    SchemaType,
    SchemaVersion,
    SubjectSummary,
)
from app.security.audit import audited
from app.store.models import Role

router = APIRouter(prefix="/clusters/{cluster}", tags=["schemas", "acls"])

ClusterDep = Annotated[str, Depends(resolve_cluster)]


def _client(cluster: str, registry: RegistryDep, settings: SettingsDep) -> SchemaRegistryClient:
    config = registry.get(cluster)
    if config.schema_registry is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "No Schema Registry is configured for this cluster. Add a "
                "schema_registry block to clusters.yaml to browse subjects."
            ),
        )
    return SchemaRegistryClient(config.schema_registry, timeout=settings.admin_timeout_seconds)


class SubjectListResponse(BaseModel):
    subjects: list[str]


class SchemaDiff(BaseModel):
    subject: str
    from_version: int
    to_version: int
    unified: str
    added: int
    removed: int


class CompatibilityRequest(BaseModel):
    schema_text: str
    schema_type: SchemaType = SchemaType.AVRO


class CompatibilityResponse(BaseModel):
    compatible: bool
    messages: list[str]
    level: str | None = None


@router.get("/schemas/subjects", response_model=SubjectListResponse, summary="List subjects")
async def list_subjects(
    cluster: ClusterDep, registry: RegistryDep, settings: SettingsDep, _principal: PrincipalDep
) -> SubjectListResponse:
    try:
        return SubjectListResponse(
            subjects=await _client(cluster, registry, settings).list_subjects()
        )
    except SchemaRegistryError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc


@router.get("/schemas/subjects/{subject}", response_model=SubjectSummary, summary="Subject detail")
async def get_subject(
    cluster: ClusterDep,
    subject: str,
    registry: RegistryDep,
    settings: SettingsDep,
    _principal: PrincipalDep,
) -> SubjectSummary:
    try:
        return await _client(cluster, registry, settings).summarise(subject)
    except SchemaRegistryError as exc:
        code = status.HTTP_404_NOT_FOUND if exc.status_code == 404 else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=code, detail=exc.message) from exc


@router.get(
    "/schemas/subjects/{subject}/versions/{version}",
    response_model=SchemaVersion,
    summary="One schema version",
)
async def get_version(
    cluster: ClusterDep,
    subject: str,
    version: str,
    registry: RegistryDep,
    settings: SettingsDep,
    _principal: PrincipalDep,
) -> SchemaVersion:
    try:
        return await _client(cluster, registry, settings).get_version(subject, version)
    except SchemaRegistryError as exc:
        code = status.HTTP_404_NOT_FOUND if exc.status_code == 404 else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=code, detail=exc.message) from exc


@router.get(
    "/schemas/subjects/{subject}/diff", response_model=SchemaDiff, summary="Diff two versions"
)
async def diff_versions(
    cluster: ClusterDep,
    subject: str,
    registry: RegistryDep,
    settings: SettingsDep,
    _principal: PrincipalDep,
    from_version: Annotated[int, Query(alias="from")],
    to_version: Annotated[int, Query(alias="to")],
) -> SchemaDiff:
    client = _client(cluster, registry, settings)
    try:
        left = await client.get_version(subject, from_version)
        right = await client.get_version(subject, to_version)
    except SchemaRegistryError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    def pretty(text: str) -> list[str]:
        # Schemas are stored as one long line; expand so the diff is readable.
        import json

        try:
            return json.dumps(json.loads(text), indent=2, sort_keys=True).splitlines()
        except (ValueError, TypeError):
            return text.splitlines()

    left_lines = pretty(left.schema_text)
    right_lines = pretty(right.schema_text)
    diff = list(
        difflib.unified_diff(
            left_lines,
            right_lines,
            fromfile=f"{subject} v{from_version}",
            tofile=f"{subject} v{to_version}",
            lineterm="",
        )
    )

    return SchemaDiff(
        subject=subject,
        from_version=from_version,
        to_version=to_version,
        unified="\n".join(diff),
        added=sum(1 for line in diff if line.startswith("+") and not line.startswith("+++")),
        removed=sum(1 for line in diff if line.startswith("-") and not line.startswith("---")),
    )


@router.post(
    "/schemas/subjects/{subject}/compatibility",
    response_model=CompatibilityResponse,
    summary="Check a candidate schema",
)
async def check_compatibility(
    cluster: ClusterDep,
    subject: str,
    payload: CompatibilityRequest,
    registry: RegistryDep,
    settings: SettingsDep,
    _principal: PrincipalDep,
) -> CompatibilityResponse:
    """Read-only: the registry evaluates the candidate without registering it."""
    client = _client(cluster, registry, settings)
    try:
        compatible, messages = await client.check_compatibility(
            subject, payload.schema_text, payload.schema_type
        )
        level = await client.compatibility(subject)
    except SchemaRegistryError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    return CompatibilityResponse(compatible=compatible, messages=messages, level=level)


# --- ACLs -----------------------------------------------------------------


class AclRequest(BaseModel):
    resource_type: AclResourceType
    resource_name: str
    pattern_type: AclPattern = AclPattern.LITERAL
    principal: str
    host: str = "*"
    operation: str
    permission: str


@router.get("/acls", response_model=AclListResponse, summary="List ACLs")
async def list_acls(
    cluster: ClusterDep,
    gates: GatesDep,
    _principal: PrincipalDep,
    resource_type: Annotated[AclResourceType, Query()] = AclResourceType.ANY,
    resource_name: Annotated[str | None, Query()] = None,
    principal_filter: Annotated[str | None, Query(alias="principal")] = None,
) -> AclListResponse:
    gate = await gates.get(cluster)
    try:
        return await AclOps(gate).list_acls(
            resource_type=resource_type,
            resource_name=resource_name,
            principal=principal_filter,
        )
    except KafkaGateError as exc:
        return AclListResponse(acls=[], supported=False, message=exc.message)


@router.post("/acls", status_code=201, summary="Create an ACL")
async def create_acl(
    request: Request,
    cluster: ClusterDep,
    payload: AclRequest,
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
        action="acl.create",
        target=f"{payload.resource_type}:{payload.resource_name}",
    )
    gate = await gates.get(cluster)

    with audited(
        request.app.state.engine,
        principal=principal,
        action="acl.create",
        cluster=cluster,
        target=f"{payload.resource_type}:{payload.resource_name}",
        source_ip=_client_ip(request),
    ) as context:
        try:
            await AclOps(gate).create_acl(**payload.model_dump())
        except KafkaGateError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message
            ) from exc
        context["after"] = payload.model_dump()

    gates.invalidate(cluster)
    return {"status": "created"}


@router.post("/acls/delete", summary="Delete an ACL")
async def delete_acl(
    request: Request,
    cluster: ClusterDep,
    payload: AclRequest,
    principal: PrincipalDep,
    registry: RegistryDep,
    settings: SettingsDep,
    gates: GatesDep,
) -> dict[str, int | str]:
    _guard(
        request,
        cluster,
        principal,
        registry,
        settings,
        required=Role.ADMIN,
        action="acl.delete",
        target=f"{payload.resource_type}:{payload.resource_name}",
    )
    gate = await gates.get(cluster)

    with audited(
        request.app.state.engine,
        principal=principal,
        action="acl.delete",
        cluster=cluster,
        target=f"{payload.resource_type}:{payload.resource_name}",
        before=payload.model_dump(),
        source_ip=_client_ip(request),
    ) as context:
        try:
            removed = await AclOps(gate).delete_acl(**payload.model_dump())
        except KafkaGateError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message
            ) from exc
        context["after"] = {"removed": removed}

    gates.invalidate(cluster)
    return {"status": "deleted", "removed": removed}


@router.get("/acls/options", summary="Valid ACL operations and permissions")
async def acl_options(_principal: PrincipalDep) -> dict[str, list[str]]:
    return {
        "operations": available_operations(),
        "permissions": available_permissions(),
        "resource_types": [item.value for item in AclResourceType],
        "pattern_types": [item.value for item in AclPattern],
    }
