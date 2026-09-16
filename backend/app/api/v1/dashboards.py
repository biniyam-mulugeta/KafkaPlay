"""Custom dashboards, flow map and latency tracer."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.deps import DbDep, GatesDep, PrincipalDep, RegistryDep, SettingsDep, resolve_cluster
from app.dashboards.panels import PanelResult, PanelSpec, build_panel
from app.flowmap.infer import FlowMap, build_flow_map
from app.kafka.errors import KafkaGateError
from app.search.scan import MessageScanner, ScanRequest, StartFrom
from app.security.audit import audited
from app.security.masking import build_masker
from app.store.models import Dashboard, Role
from app.tracer.join import TraceRequest, TraceResult, correlate

router = APIRouter(prefix="/clusters/{cluster}", tags=["dashboards"])

ClusterDep = Annotated[str, Depends(resolve_cluster)]


class DashboardModel(BaseModel):
    id: int
    name: str
    cluster: str
    description: str | None
    panels: list[PanelSpec]
    created_at: datetime
    updated_at: datetime
    created_by: str


class DashboardListResponse(BaseModel):
    dashboards: list[DashboardModel]


class SaveDashboardRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    panels: list[PanelSpec] = Field(default_factory=list)


def _to_model(row: Dashboard) -> DashboardModel:
    try:
        panels = [PanelSpec.model_validate(item) for item in json.loads(row.panels_json)]
    except (json.JSONDecodeError, ValueError):
        panels = []
    return DashboardModel(
        id=row.id or 0,
        name=row.name,
        cluster=row.cluster,
        description=row.description,
        panels=panels,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
    )


@router.get("/dashboards", response_model=DashboardListResponse, summary="List dashboards")
async def list_dashboards(
    cluster: ClusterDep, _principal: PrincipalDep, db: DbDep
) -> DashboardListResponse:
    rows = db.exec(
        select(Dashboard).where(Dashboard.cluster == cluster).order_by(col(Dashboard.name))
    ).all()
    return DashboardListResponse(dashboards=[_to_model(row) for row in rows])


@router.post(
    "/dashboards", response_model=DashboardModel, status_code=201, summary="Create a dashboard"
)
async def create_dashboard(
    request: Request,
    cluster: ClusterDep,
    payload: SaveDashboardRequest,
    principal: PrincipalDep,
    db: DbDep,
) -> DashboardModel:
    dashboard = Dashboard(
        name=payload.name,
        cluster=cluster,
        description=payload.description,
        panels_json=json.dumps([panel.model_dump(mode="json") for panel in payload.panels]),
        created_by=principal.username,
    )
    with audited(
        request.app.state.engine,
        principal=principal,
        action="dashboard.create",
        cluster=cluster,
        target=payload.name,
        source_ip=request.client.host if request.client else None,
    ) as context:
        db.add(dashboard)
        db.commit()
        db.refresh(dashboard)
        context["after"] = {"panels": len(payload.panels)}
    return _to_model(dashboard)


@router.put(
    "/dashboards/{dashboard_id}", response_model=DashboardModel, summary="Replace a dashboard"
)
async def update_dashboard(
    request: Request,
    cluster: ClusterDep,
    dashboard_id: int,
    payload: SaveDashboardRequest,
    principal: PrincipalDep,
    db: DbDep,
) -> DashboardModel:
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None or dashboard.cluster != cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such dashboard")

    from app.store.models import utcnow

    with audited(
        request.app.state.engine,
        principal=principal,
        action="dashboard.update",
        cluster=cluster,
        target=dashboard.name,
        source_ip=request.client.host if request.client else None,
    ):
        dashboard.name = payload.name
        dashboard.description = payload.description
        dashboard.panels_json = json.dumps(
            [panel.model_dump(mode="json") for panel in payload.panels]
        )
        dashboard.updated_at = utcnow()
        db.add(dashboard)
        db.commit()
        db.refresh(dashboard)

    return _to_model(dashboard)


@router.delete("/dashboards/{dashboard_id}", status_code=204, summary="Delete a dashboard")
async def delete_dashboard(
    request: Request,
    cluster: ClusterDep,
    dashboard_id: int,
    principal: PrincipalDep,
    db: DbDep,
) -> None:
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None or dashboard.cluster != cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such dashboard")
    with audited(
        request.app.state.engine,
        principal=principal,
        action="dashboard.delete",
        cluster=cluster,
        target=dashboard.name,
        source_ip=request.client.host if request.client else None,
    ):
        db.delete(dashboard)
        db.commit()


@router.post("/dashboards/render", response_model=list[PanelResult], summary="Render panels")
async def render_panels(
    cluster: ClusterDep,
    panels: list[PanelSpec],
    registry: RegistryDep,
    settings: SettingsDep,
    _principal: PrincipalDep,
) -> list[PanelResult]:
    """Run each panel's scan and build its result.

    Panels reading the same topic with the same window share one scan, so a
    dashboard with eight panels over one topic costs one pass, not eight.
    """
    config = registry.get(cluster)
    masker = build_masker(
        config.mask_rules,
        cluster_enabled=config.masking_enabled,
        global_enabled=settings.masking_enabled,
    )
    scanner = MessageScanner(config, timeout_seconds=settings.admin_timeout_seconds)

    shared: dict[tuple[str, int, int], object] = {}
    results: list[PanelResult] = []

    for panel in panels:
        cache_key = (panel.topic, panel.window_minutes, panel.max_messages)
        scan = shared.get(cache_key)
        if scan is None:
            try:
                scan = await scanner.scan(
                    ScanRequest(
                        topic=panel.topic,
                        partitions=panel.partitions,
                        start_from=StartFrom.NEWEST,
                        filter_expression=panel.filter,
                        max_results=panel.max_messages,
                        max_scanned=panel.max_messages * 4,
                        max_seconds=min(30.0, settings.admin_timeout_seconds * 2),
                    ),
                    masker=masker,
                )
                shared[cache_key] = scan
            except KafkaGateError as exc:
                results.append(
                    PanelResult(
                        id=panel.id,
                        title=panel.title,
                        type=panel.type,
                        topic=panel.topic,
                        sampled=0,
                        matched=0,
                        elapsed_seconds=0.0,
                        stop_reason="error",
                        error=exc.message,
                    )
                )
                continue

        results.append(
            build_panel(
                panel,
                scan.messages,  # type: ignore[attr-defined]
                sampled=scan.scanned,  # type: ignore[attr-defined]
                elapsed_seconds=scan.elapsed_seconds,  # type: ignore[attr-defined]
                stop_reason=str(scan.stop_reason),  # type: ignore[attr-defined]
            )
        )

    return results


@router.get("/flow-map", response_model=FlowMap, summary="Topic flow map")
async def get_flow_map(
    request: Request,
    cluster: ClusterDep,
    gates: GatesDep,
    registry: RegistryDep,
    _principal: PrincipalDep,
    window_minutes: Annotated[int, Query(ge=1, le=1440)] = 30,
) -> FlowMap:
    gate = await gates.get(cluster)
    return await build_flow_map(
        gate, registry.get(cluster), request.app.state.engine, window_minutes=window_minutes
    )


@router.post("/trace", response_model=TraceResult, summary="Topic-to-topic latency trace")
async def trace_latency(
    cluster: ClusterDep,
    payload: TraceRequest,
    registry: RegistryDep,
    settings: SettingsDep,
    principal: PrincipalDep,
) -> TraceResult:
    """Correlate two topics by key and report the latency between them.

    Operator-gated because it runs two full scans; a viewer browsing the UI
    should not be able to start one by accident.
    """
    if not principal.has_role(Role.OPERATOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tracing runs two scans and requires the operator role",
        )

    config = registry.get(cluster)
    # Tracing joins on keys that may be masked in display; the join needs the
    # true values, and nothing from this scan is returned to the browser.
    from app.security.masking import Masker

    scanner = MessageScanner(config, timeout_seconds=settings.admin_timeout_seconds)
    unmasked = Masker([], enabled=False)

    def scan_request(topic: str) -> ScanRequest:
        return ScanRequest(
            topic=topic,
            start_from=StartFrom.NEWEST,
            max_results=payload.max_messages,
            max_scanned=payload.max_messages * 4,
            max_seconds=payload.max_seconds,
        )

    try:
        source = await scanner.scan(scan_request(payload.source_topic), masker=unmasked)
        target = await scanner.scan(scan_request(payload.target_topic), masker=unmasked)
    except KafkaGateError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

    return correlate(
        payload,
        source.messages,
        target.messages,
        source_scanned=source.scanned,
        target_scanned=target.scanned,
    )
