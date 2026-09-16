"""Alert rules and the notification centre."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.deps import DbDep, PrincipalDep, SettingsDep
from app.security.audit import audited
from app.store.models import (
    AlertFiring,
    AlertKind,
    AlertRule,
    AlertSeverity,
    AlertState,
    Role,
    utcnow,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


class RuleModel(BaseModel):
    id: int
    name: str
    cluster: str
    kind: AlertKind
    severity: AlertSeverity
    enabled: bool
    topic: str | None
    group_id: str | None
    threshold: float
    for_seconds: int
    cooldown_seconds: int
    notify_webhook: bool
    notify_slack: bool
    notify_teams: bool
    notify_email: str | None
    state: AlertState
    since: datetime | None
    last_value: float | None
    created_by: str


class RuleListResponse(BaseModel):
    rules: list[RuleModel]
    notifications_configured: bool


class CreateRuleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    cluster: str
    kind: AlertKind
    severity: AlertSeverity = AlertSeverity.WARNING
    topic: str | None = None
    group_id: str | None = None
    threshold: float = 0.0
    for_seconds: int = Field(default=60, ge=0, le=86400)
    cooldown_seconds: int = Field(default=900, ge=0, le=86400)
    notify_webhook: bool = False
    notify_slack: bool = False
    notify_teams: bool = False
    notify_email: str | None = None
    enabled: bool = True


class UpdateRuleRequest(BaseModel):
    enabled: bool | None = None
    threshold: float | None = None
    severity: AlertSeverity | None = None
    for_seconds: int | None = Field(default=None, ge=0, le=86400)
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)
    notify_webhook: bool | None = None
    notify_slack: bool | None = None
    notify_teams: bool | None = None
    notify_email: str | None = None


class FiringModel(BaseModel):
    id: int
    rule_id: int
    rule_name: str
    cluster: str
    severity: AlertSeverity
    state: AlertState
    at: datetime
    value: float | None
    message: str
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    notified: bool
    notify_error: str | None


class FiringListResponse(BaseModel):
    firings: list[FiringModel]
    unacknowledged: int


def _require_operator(principal: PrincipalDep) -> None:
    if not principal.has_role(Role.OPERATOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="managing alert rules requires the operator role",
        )


@router.get("/rules", response_model=RuleListResponse, summary="List alert rules")
async def list_rules(
    _principal: PrincipalDep, db: DbDep, settings: SettingsDep
) -> RuleListResponse:
    rows = db.exec(select(AlertRule).order_by(col(AlertRule.name))).all()
    configured = bool(
        settings.webhook_url
        or settings.slack_webhook_url
        or settings.teams_webhook_url
        or settings.smtp_host
    )
    return RuleListResponse(
        rules=[RuleModel.model_validate(row, from_attributes=True) for row in rows],
        notifications_configured=configured,
    )


@router.post("/rules", response_model=RuleModel, status_code=201, summary="Create a rule")
async def create_rule(
    request: Request, payload: CreateRuleRequest, principal: PrincipalDep, db: DbDep
) -> RuleModel:
    _require_operator(principal)

    # A rule that names nothing to watch would silently never fire.
    if payload.kind in (AlertKind.LAG_ABOVE, AlertKind.LAG_VELOCITY) and not payload.group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{payload.kind} rules need a consumer group",
        )
    if payload.kind is AlertKind.THROUGHPUT_ZERO and not payload.topic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="throughput_zero rules need a topic",
        )

    rule = AlertRule(**payload.model_dump(), created_by=principal.username)

    with audited(
        request.app.state.engine,
        principal=principal,
        action="alert.rule.create",
        cluster=payload.cluster,
        target=payload.name,
        source_ip=request.client.host if request.client else None,
    ) as context:
        db.add(rule)
        db.commit()
        db.refresh(rule)
        context["after"] = {"kind": str(payload.kind), "threshold": payload.threshold}

    return RuleModel.model_validate(rule, from_attributes=True)


@router.patch("/rules/{rule_id}", response_model=RuleModel, summary="Update a rule")
async def update_rule(
    request: Request,
    rule_id: int,
    payload: UpdateRuleRequest,
    principal: PrincipalDep,
    db: DbDep,
) -> RuleModel:
    _require_operator(principal)
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such rule")

    before = {"enabled": rule.enabled, "threshold": rule.threshold}

    with audited(
        request.app.state.engine,
        principal=principal,
        action="alert.rule.update",
        cluster=rule.cluster,
        target=rule.name,
        before=before,
        source_ip=request.client.host if request.client else None,
    ) as context:
        for name, value in payload.model_dump(exclude_none=True).items():
            setattr(rule, name, value)
        # Re-arm: a threshold change should not inherit the old hold timer.
        rule.state = AlertState.OK
        rule.since = None
        db.add(rule)
        db.commit()
        db.refresh(rule)
        context["after"] = {"enabled": rule.enabled, "threshold": rule.threshold}

    return RuleModel.model_validate(rule, from_attributes=True)


@router.delete("/rules/{rule_id}", status_code=204, summary="Delete a rule")
async def delete_rule(request: Request, rule_id: int, principal: PrincipalDep, db: DbDep) -> None:
    _require_operator(principal)
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such rule")

    with audited(
        request.app.state.engine,
        principal=principal,
        action="alert.rule.delete",
        cluster=rule.cluster,
        target=rule.name,
        before={"kind": str(rule.kind), "threshold": rule.threshold},
        source_ip=request.client.host if request.client else None,
    ):
        db.delete(rule)
        db.commit()


@router.get("/firings", response_model=FiringListResponse, summary="Notification centre")
async def list_firings(
    _principal: PrincipalDep,
    db: DbDep,
    days: Annotated[int, Query(ge=1, le=365)] = 7,
    only_unacknowledged: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> FiringListResponse:
    since = datetime.now(UTC) - timedelta(days=days)
    statement = select(AlertFiring).where(col(AlertFiring.at) >= since)
    if only_unacknowledged:
        statement = statement.where(col(AlertFiring.acknowledged_at).is_(None))

    rows = db.exec(statement.order_by(col(AlertFiring.at).desc()).limit(limit)).all()
    unacknowledged = len(
        db.exec(
            select(AlertFiring)
            .where(col(AlertFiring.at) >= since)
            .where(col(AlertFiring.acknowledged_at).is_(None))
            .where(AlertFiring.state == AlertState.FIRING)
        ).all()
    )

    return FiringListResponse(
        firings=[FiringModel.model_validate(row, from_attributes=True) for row in rows],
        unacknowledged=unacknowledged,
    )


@router.post("/firings/{firing_id}/acknowledge", status_code=204, summary="Acknowledge")
async def acknowledge(firing_id: int, principal: PrincipalDep, db: DbDep) -> None:
    firing = db.get(AlertFiring, firing_id)
    if firing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such firing")
    firing.acknowledged_at = utcnow()
    firing.acknowledged_by = principal.username
    db.add(firing)
    db.commit()


@router.post("/test-notification", summary="Send a test notification")
async def test_notification(
    request: Request, principal: PrincipalDep, settings: SettingsDep
) -> dict[str, object]:
    """Deliver one synthetic notification to every configured sink."""
    _require_operator(principal)
    notifier = getattr(request.app.state, "notifier", None)
    if notifier is None or not notifier.any_configured:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "No notification sink is configured. Set WEBHOOK_URL, SLACK_WEBHOOK_URL, "
                "TEAMS_WEBHOOK_URL or SMTP_HOST in .env."
            ),
        )

    sample = AlertFiring(
        rule_id=0,
        rule_name="test notification",
        cluster="-",
        severity=AlertSeverity.INFO,
        state=AlertState.FIRING,
        value=0.0,
        message=f"Test notification from {settings.app_name}, requested by {principal.username}.",
    )
    results = await notifier.send_test(sample)
    return {"results": results}


class AlertKindInfo(BaseModel):
    kind: AlertKind
    label: str
    needs_group: bool
    needs_topic: bool
    threshold_hint: str


@router.get("/kinds", response_model=list[AlertKindInfo], summary="Supported rule kinds")
async def list_kinds(_principal: PrincipalDep) -> list[AlertKindInfo]:
    return [
        AlertKindInfo(
            kind=AlertKind.LAG_ABOVE,
            label="Consumer lag above a threshold",
            needs_group=True,
            needs_topic=False,
            threshold_hint="messages",
        ),
        AlertKindInfo(
            kind=AlertKind.LAG_VELOCITY,
            label="Lag growing faster than",
            needs_group=True,
            needs_topic=False,
            threshold_hint="messages per second",
        ),
        AlertKindInfo(
            kind=AlertKind.UNDER_REPLICATED,
            label="Under-replicated partitions above",
            needs_group=False,
            needs_topic=False,
            threshold_hint="partitions",
        ),
        AlertKindInfo(
            kind=AlertKind.OFFLINE_PARTITIONS,
            label="Offline partitions above",
            needs_group=False,
            needs_topic=False,
            threshold_hint="partitions",
        ),
        AlertKindInfo(
            kind=AlertKind.BROKER_DOWN,
            label="Fewer brokers than expected",
            needs_group=False,
            needs_topic=False,
            threshold_hint="expected broker count",
        ),
        AlertKindInfo(
            kind=AlertKind.THROUGHPUT_ZERO,
            label="Topic throughput at or below",
            needs_group=False,
            needs_topic=True,
            threshold_hint="messages per second",
        ),
    ]
