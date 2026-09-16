"""Cluster listing.

Read-only in M1. Connection details are deliberately *not* returned -- a viewer
must never be able to read SASL credentials out of the API. Only the facts the
UI needs to render a switcher and a banner are exposed.
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlmodel import select

from app.api.deps import AdminDep, DbDep, PrincipalDep, RegistryDep, SettingsDep
from app.clusters.models import ClusterConfig, SecurityProtocol
from app.clusters.store import to_config
from app.kafka.errors import KafkaGateError
from app.kafka.gate import KafkaGate
from app.security.audit import audited
from app.store.models import StoredCluster

router = APIRouter(prefix="/clusters", tags=["clusters"])


class ClusterSummary(BaseModel):
    name: str
    label: str
    security_protocol: SecurityProtocol
    sasl_mechanism: str | None = None
    has_schema_registry: bool
    read_only: bool
    masking_enabled: bool
    # Filled in from a live probe in M2; null means "not contacted yet".
    reachable: bool | None = None


class ClusterListResponse(BaseModel):
    clusters: list[ClusterSummary]


def _summarise(cluster: ClusterConfig, *, global_read_only: bool) -> ClusterSummary:
    return ClusterSummary(
        name=cluster.name,
        label=cluster.display_name,
        security_protocol=cluster.security_protocol,
        sasl_mechanism=str(cluster.sasl.mechanism) if cluster.sasl else None,
        has_schema_registry=cluster.schema_registry is not None,
        read_only=cluster.read_only or global_read_only,
        masking_enabled=cluster.masking_enabled,
    )


@router.get("", response_model=ClusterListResponse, summary="List configured clusters")
def list_clusters(
    _principal: PrincipalDep,
    registry: RegistryDep,
    settings: SettingsDep,
) -> ClusterListResponse:
    return ClusterListResponse(
        clusters=[
            _summarise(cluster, global_read_only=settings.read_only) for cluster in registry.list()
        ]
    )


class ClusterInput(BaseModel):
    """A cluster defined from the UI."""

    name: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._-]+$")
    label: str | None = None
    bootstrap_servers: str = Field(min_length=1)
    security_protocol: SecurityProtocol = SecurityProtocol.PLAINTEXT
    sasl_mechanism: str | None = None
    sasl_username: str | None = None
    sasl_password: str | None = None
    tls_ca_location: str | None = None
    tls_insecure_skip_verify: bool = False
    schema_registry_url: str | None = None
    schema_registry_username: str | None = None
    schema_registry_password: str | None = None
    read_only: bool = False
    masking_enabled: bool = True


class ConnectionTest(BaseModel):
    ok: bool
    brokers: int = 0
    cluster_id: str | None = None
    topics: int = 0
    error: str | None = None


def _row(payload: ClusterInput, username: str) -> StoredCluster:
    return StoredCluster(
        name=payload.name,
        label=payload.label,
        bootstrap_servers=payload.bootstrap_servers,
        security_protocol=str(payload.security_protocol),
        sasl_mechanism=payload.sasl_mechanism,
        sasl_username=payload.sasl_username,
        sasl_password=payload.sasl_password,
        tls_ca_location=payload.tls_ca_location,
        tls_insecure_skip_verify=payload.tls_insecure_skip_verify,
        schema_registry_url=payload.schema_registry_url,
        schema_registry_username=payload.schema_registry_username,
        schema_registry_password=payload.schema_registry_password,
        read_only=payload.read_only,
        masking_enabled=payload.masking_enabled,
        created_by=username,
    )


async def _probe(config: ClusterConfig, timeout: float) -> ConnectionTest:
    """Contact the broker once and report what came back."""
    gate = KafkaGate(config, timeout_seconds=timeout)
    try:
        info = await gate.describe_cluster()
        return ConnectionTest(
            ok=True,
            brokers=len(info.brokers),
            cluster_id=info.cluster_id,
            topics=info.topic_count,
        )
    except KafkaGateError as exc:
        hint = f" {exc.hint}" if exc.hint else ""
        return ConnectionTest(ok=False, error=f"{exc.message}.{hint}".strip())
    except Exception as exc:
        return ConnectionTest(ok=False, error=str(exc))
    finally:
        gate.close()


@router.post("/test", response_model=ConnectionTest, summary="Test a connection")
async def test_connection(
    payload: ClusterInput, _admin: AdminDep, settings: SettingsDep
) -> ConnectionTest:
    """Try the settings without saving them, so a typo is caught immediately."""
    try:
        config = to_config(_row(payload, "test"))
    except Exception as exc:
        return ConnectionTest(ok=False, error=str(exc))
    return await _probe(config, settings.admin_timeout_seconds)


@router.post("", response_model=ClusterSummary, status_code=201, summary="Add a cluster")
async def add_cluster(
    request: Request,
    payload: ClusterInput,
    admin: AdminDep,
    db: DbDep,
    registry: RegistryDep,
    settings: SettingsDep,
) -> ClusterSummary:
    if registry.has(payload.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a cluster named {payload.name!r} already exists",
        )

    row = _row(payload, admin.username)
    try:
        config = to_config(row)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    with audited(
        request.app.state.engine,
        principal=admin,
        action="cluster.create",
        cluster=payload.name,
        target=payload.name,
        source_ip=request.client.host if request.client else None,
    ) as context:
        db.add(row)
        db.commit()
        registry.upsert(config)
        # Credentials are deliberately not recorded in the audit snapshot.
        context["after"] = {
            "bootstrap_servers": payload.bootstrap_servers,
            "security_protocol": str(payload.security_protocol),
            "read_only": payload.read_only,
        }

    return _summarise(config, global_read_only=settings.read_only)


@router.delete("/{name}", status_code=204, summary="Remove a cluster")
async def remove_cluster(
    request: Request, name: str, admin: AdminDep, db: DbDep, registry: RegistryDep
) -> None:
    row = db.exec(select(StoredCluster).where(StoredCluster.name == name)).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"{name!r} is not a cluster added here. Clusters from clusters.yaml "
                "are removed by editing that file."
            ),
        )

    with audited(
        request.app.state.engine,
        principal=admin,
        action="cluster.delete",
        cluster=name,
        target=name,
        before={"bootstrap_servers": row.bootstrap_servers},
        source_ip=request.client.host if request.client else None,
    ):
        db.delete(row)
        db.commit()
        with contextlib.suppress(KeyError):
            registry.remove(name)


@router.get("/{name}/health", response_model=ConnectionTest, summary="Check a cluster")
async def cluster_health(
    name: str, _principal: PrincipalDep, registry: RegistryDep, settings: SettingsDep
) -> ConnectionTest:
    try:
        config = registry.get(name)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return await _probe(config, settings.admin_timeout_seconds)
