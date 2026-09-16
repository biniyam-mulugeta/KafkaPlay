"""Cluster listing.

Read-only in M1. Connection details are deliberately *not* returned -- a viewer
must never be able to read SASL credentials out of the API. Only the facts the
UI needs to render a switcher and a banner are exposed.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import PrincipalDep, RegistryDep, SettingsDep
from app.clusters.models import ClusterConfig, SecurityProtocol

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
