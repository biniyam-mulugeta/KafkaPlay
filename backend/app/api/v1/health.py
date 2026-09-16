"""Liveness and readiness.

Deliberately separate: /healthz says the process is alive, /readyz says it can
serve. Neither touches a broker -- an unreachable Kafka cluster is a degraded
state reported per-cluster in the API, not a reason to fail a container probe
and get the console restarted in a loop.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from app.api.deps import RegistryDep, SettingsDep, get_db

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str
    version: str


class ReadyCheck(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: list[ReadyCheck]


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
def healthz(settings: SettingsDep) -> HealthResponse:
    from app import __version__

    return HealthResponse(status="ok", app=settings.app_name, version=__version__)


@router.get("/readyz", response_model=ReadyResponse, summary="Readiness probe")
def readyz(
    response: Response,
    settings: SettingsDep,
    registry: RegistryDep,
    db: Annotated[Session, Depends(get_db)],
) -> ReadyResponse:
    checks: list[ReadyCheck] = []

    try:
        db.exec(text("SELECT 1"))  # type: ignore[call-overload]
        checks.append(ReadyCheck(name="database", ok=True))
    except Exception as exc:  # probe must never raise
        checks.append(ReadyCheck(name="database", ok=False, detail=str(exc)))

    # An empty registry is a valid first-run state, not a failure: an admin can
    # add the first cluster from the UI.
    checks.append(
        ReadyCheck(
            name="clusters",
            ok=True,
            detail=(
                "no clusters configured yet" if registry.is_empty else f"{len(registry)} configured"
            ),
        )
    )

    theme_ok = settings.theme_dir.is_dir()
    checks.append(
        ReadyCheck(
            name="theme",
            ok=theme_ok,
            detail=None if theme_ok else f"theme directory not found: {settings.theme_dir}",
        )
    )

    ready = all(check.ok for check in checks)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status="ready" if ready else "not_ready", checks=checks)
