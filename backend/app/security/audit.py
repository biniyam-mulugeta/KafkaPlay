"""The audit log.

Every mutating action records who did what, when, against which cluster, the
before and after state, and the outcome -- including refusals, which are often
the more interesting entries.

Two rules:

1. Append-only. Rows are never updated or deleted by application code.
2. A reveal of a masked value records *that* it happened and what it was
   about, never the revealed value itself. Otherwise the audit log would
   become the personal-data store that masking exists to avoid.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session

from app.auth.rbac import Principal
from app.logging import get_logger
from app.store.models import AuditEntry, AuditResult

log = get_logger(__name__)

# Values that must never be written into before/after snapshots, even if a
# caller passes them in.
_NEVER_RECORD = frozenset(
    {"password", "sasl_password", "client_secret", "token", "value", "key", "payload"}
)


def _scrub(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            key: ("***" if key.lower() in _NEVER_RECORD else _scrub(value))
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_scrub(item) for item in data]
    return data


def _dump(data: Any) -> str | None:
    if data is None:
        return None
    try:
        return json.dumps(_scrub(data), default=str, ensure_ascii=False)[:8000]
    except (TypeError, ValueError):
        return str(data)[:8000]


def record(
    engine: Engine,
    *,
    principal: Principal,
    action: str,
    result: AuditResult,
    cluster: str | None = None,
    target: str | None = None,
    before: Any = None,
    after: Any = None,
    detail: str | None = None,
    source_ip: str | None = None,
) -> None:
    """Write one audit row. Never raises into the caller's path."""
    entry = AuditEntry(
        username=principal.username,
        role=principal.role,
        cluster=cluster,
        action=action,
        target=target,
        result=result,
        before=_dump(before),
        after=_dump(after),
        detail=detail,
        source_ip=source_ip,
    )
    try:
        with Session(engine) as session:
            session.add(entry)
            session.commit()
    except Exception as exc:
        # An audit failure must not silently swallow the action's own outcome,
        # but it also must not mask it -- log loudly and carry on.
        log.error("audit_write_failed", action=action, error=str(exc))

    log.info(
        "audit",
        action=action,
        result=str(result),
        username=principal.username,
        cluster=cluster,
        target=target,
    )


@contextmanager
def audited(
    engine: Engine,
    *,
    principal: Principal,
    action: str,
    cluster: str | None = None,
    target: str | None = None,
    before: Any = None,
    source_ip: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Record success or failure around a mutating operation.

    The caller may put an ``after`` snapshot into the yielded dict. An
    exception is recorded as a failure and re-raised, so a failed write is
    still audited.
    """
    context: dict[str, Any] = {"after": None, "detail": None}
    try:
        yield context
    except Exception as exc:
        record(
            engine,
            principal=principal,
            action=action,
            result=AuditResult.FAILED,
            cluster=cluster,
            target=target,
            before=before,
            detail=f"{type(exc).__name__}: {exc}"[:2000],
            source_ip=source_ip,
        )
        raise
    else:
        record(
            engine,
            principal=principal,
            action=action,
            result=AuditResult.SUCCESS,
            cluster=cluster,
            target=target,
            before=before,
            after=context.get("after"),
            detail=context.get("detail"),
            source_ip=source_ip,
        )


def record_denial(
    engine: Engine,
    *,
    principal: Principal,
    action: str,
    reason: str,
    cluster: str | None = None,
    target: str | None = None,
    source_ip: str | None = None,
) -> None:
    """A refused action is worth recording: it is evidence of an attempt."""
    record(
        engine,
        principal=principal,
        action=action,
        result=AuditResult.DENIED,
        cluster=cluster,
        target=target,
        detail=reason,
        source_ip=source_ip,
    )
