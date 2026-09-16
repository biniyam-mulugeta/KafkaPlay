"""Viewing and exporting the audit log."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.api.deps import AdminDep, PrincipalDep
from app.store.models import AuditEntry, AuditResult, Role

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntryModel(BaseModel):
    id: int
    at: datetime
    username: str
    role: Role
    cluster: str | None
    action: str
    target: str | None
    result: AuditResult
    before: str | None
    after: str | None
    detail: str | None
    source_ip: str | None


class AuditListResponse(BaseModel):
    entries: list[AuditEntryModel]
    total: int


def _query(
    session: Session,
    *,
    cluster: str | None,
    action: str | None,
    username: str | None,
    result: AuditResult | None,
    days: int,
) -> Any:
    since = datetime.now(UTC) - timedelta(days=days)
    statement = select(AuditEntry).where(col(AuditEntry.at) >= since)
    if cluster:
        statement = statement.where(AuditEntry.cluster == cluster)
    if action:
        statement = statement.where(col(AuditEntry.action).like(f"{action}%"))
    if username:
        statement = statement.where(AuditEntry.username == username)
    if result:
        statement = statement.where(AuditEntry.result == result)
    return statement


@router.get("", response_model=AuditListResponse, summary="Read the audit log")
async def list_audit(
    request: Request,
    # Viewers can see that actions happened; only admins can read the log,
    # because before/after snapshots can reveal cluster structure.
    _admin: AdminDep,
    cluster: Annotated[str | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    username: Annotated[str | None, Query()] = None,
    result: Annotated[AuditResult | None, Query()] = None,
    days: Annotated[int, Query(ge=1, le=3650)] = 30,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditListResponse:
    with Session(request.app.state.engine) as session:
        statement = _query(
            session,
            cluster=cluster,
            action=action,
            username=username,
            result=result,
            days=days,
        )
        total = len(session.exec(statement).all())
        rows = session.exec(
            statement.order_by(col(AuditEntry.at).desc()).offset(offset).limit(limit)
        ).all()

    return AuditListResponse(
        entries=[AuditEntryModel.model_validate(row, from_attributes=True) for row in rows],
        total=total,
    )


@router.get("/export", summary="Export the audit log as CSV")
async def export_audit(
    request: Request,
    _admin: AdminDep,
    cluster: Annotated[str | None, Query()] = None,
    days: Annotated[int, Query(ge=1, le=3650)] = 30,
) -> Response:
    with Session(request.app.state.engine) as session:
        rows = session.exec(
            _query(
                session, cluster=cluster, action=None, username=None, result=None, days=days
            ).order_by(col(AuditEntry.at).desc())
        ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "at",
            "username",
            "role",
            "cluster",
            "action",
            "target",
            "result",
            "before",
            "after",
            "detail",
            "source_ip",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.at.isoformat(),
                row.username,
                str(row.role),
                row.cluster or "",
                row.action,
                row.target or "",
                str(row.result),
                row.before or "",
                row.after or "",
                row.detail or "",
                row.source_ip or "",
            ]
        )

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit-{stamp}.csv"'},
    )


class AuditActionsResponse(BaseModel):
    actions: list[str]


@router.get("/actions", response_model=AuditActionsResponse, summary="Distinct action names")
async def list_actions(request: Request, _principal: PrincipalDep) -> AuditActionsResponse:
    with Session(request.app.state.engine) as session:
        rows = session.exec(select(AuditEntry.action).distinct()).all()
    return AuditActionsResponse(actions=sorted({str(row) for row in rows}))
