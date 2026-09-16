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
