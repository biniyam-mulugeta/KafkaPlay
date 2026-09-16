"""Persistent application state.

What lives here: users, audit records, saved searches, dashboards, alert rules,
and sampled offsets.

What must never live here: Kafka message keys, values, or headers. Payloads are
streamed to the browser and forgotten. The only message-derived data that may
be persisted is an aggregate from a dashboard panel that an operator has
explicitly marked persistable, and then only after masking.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}[self]

    def satisfies(self, required: Role) -> bool:
        return self.rank >= required.rank


class AuthProvider(StrEnum):
    LOCAL = "local"
    OIDC = "oidc"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    # Null for OIDC users, who never have a local password.
    password_hash: str | None = Field(default=None)
    provider: AuthProvider = Field(default=AuthProvider.LOCAL)
    role: Role = Field(default=Role.VIEWER)
    email: str | None = Field(default=None)
    display_name: str | None = Field(default=None)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = Field(default=None)


class AuditResult(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILED = "failed"


class AuditEntry(SQLModel, table=True):
    """One row per attempted write action. Append-only; never updated."""

    __tablename__ = "audit_entries"

    id: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=utcnow, index=True)
    username: str = Field(index=True)
    role: Role
    cluster: str | None = Field(default=None, index=True)
    action: str = Field(index=True, description="e.g. topic.create, group.offsets.reset")
    target: str | None = Field(default=None, description="Topic, group, or user acted upon.")
    result: AuditResult
    # JSON blobs. For a reveal action these record *that* a reveal happened and
    # what was revealed *about* -- never the revealed value itself.
    before: str | None = Field(default=None)
    after: str | None = Field(default=None)
    detail: str | None = Field(default=None)
    source_ip: str | None = Field(default=None)


class OffsetSample(SQLModel, table=True):
    """One observation of a consumer group's position and the log end.

    This is what makes lag history, velocity and throughput work with no
    Prometheus and no JMX. It stores offsets only -- numbers, never message
    content -- so it carries no personal data.

    Rows are written by the background sampler and aged out by retention.
    """

    __tablename__ = "offset_samples"

    id: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=utcnow, index=True)
    cluster: str = Field(index=True)
    group_id: str = Field(index=True)
    topic: str = Field(index=True)
    partition: int
    committed_offset: int | None = Field(default=None)
    high_watermark: int | None = Field(default=None)
    lag: int | None = Field(default=None)


class TopicOffsetSample(SQLModel, table=True):
    """Log-end offsets per partition, independent of any consumer group.

    Used for topic throughput and the partition heatmap, which must work for
    topics nobody is consuming.
    """

    __tablename__ = "topic_offset_samples"

    id: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=utcnow, index=True)
    cluster: str = Field(index=True)
    topic: str = Field(index=True)
    partition: int
    low_watermark: int | None = Field(default=None)
    high_watermark: int | None = Field(default=None)


class AlertKind(StrEnum):
    """What a rule watches.

    All of these are answerable from the built-in sampler and AdminClient, so
    alerting works without Prometheus, same as the charts.
    """

    LAG_ABOVE = "lag_above"
    LAG_VELOCITY = "lag_velocity"
    UNDER_REPLICATED = "under_replicated"
    OFFLINE_PARTITIONS = "offline_partitions"
    BROKER_DOWN = "broker_down"
    THROUGHPUT_ZERO = "throughput_zero"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertState(StrEnum):
    OK = "ok"
    FIRING = "firing"


class AlertRule(SQLModel, table=True):
    __tablename__ = "alert_rules"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    cluster: str = Field(index=True)
    kind: AlertKind
    severity: AlertSeverity = Field(default=AlertSeverity.WARNING)
    enabled: bool = Field(default=True)

    # Scope. Empty means "any".
    topic: str | None = Field(default=None)
    group_id: str | None = Field(default=None)

    threshold: float = Field(default=0.0)
    # How long the condition must hold before firing, so a single noisy
    # sample does not page anyone.
    for_seconds: int = Field(default=60)
    # Minimum gap between notifications while a rule stays firing.
    cooldown_seconds: int = Field(default=900)

    notify_webhook: bool = Field(default=False)
    notify_slack: bool = Field(default=False)
    notify_teams: bool = Field(default=False)
    notify_email: str | None = Field(default=None)

    state: AlertState = Field(default=AlertState.OK)
    since: datetime | None = Field(default=None)
    last_notified_at: datetime | None = Field(default=None)
    last_value: float | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    created_by: str = Field(default="system")


class AlertFiring(SQLModel, table=True):
    """History of state changes, so an operator can see what happened."""

    __tablename__ = "alert_firings"

    id: int | None = Field(default=None, primary_key=True)
    rule_id: int = Field(index=True)
    rule_name: str
    cluster: str = Field(index=True)
    severity: AlertSeverity
    state: AlertState
    at: datetime = Field(default_factory=utcnow, index=True)
    value: float | None = Field(default=None)
    message: str = Field(default="")
    acknowledged_at: datetime | None = Field(default=None)
    acknowledged_by: str | None = Field(default=None)
    notified: bool = Field(default=False)
    notify_error: str | None = Field(default=None)
