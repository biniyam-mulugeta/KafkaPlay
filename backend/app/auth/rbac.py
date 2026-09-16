"""Role checks and the read-only gate.

Two independent controls guard every mutating action:

1. Role  -- who you are (viewer < operator < admin).
2. Read-only -- what this deployment permits at all.

Read-only wins over role: an admin pointed at a read-only cluster still cannot
write. That ordering is deliberate, because READ_ONLY exists precisely for
people who point this console at production.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.store.models import Role


class AuthorizationError(Exception):
    """403-level failure: the caller is known but not permitted."""

    def __init__(self, message: str, *, required_role: Role | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.required_role = required_role


class ReadOnlyError(AuthorizationError):
    """The deployment or cluster forbids all writes."""


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller."""

    username: str
    role: Role
    provider: str = "local"
    # Per-cluster role overrides; falls back to `role` when a cluster is absent.
    cluster_roles: dict[str, Role] | None = None

    def role_for(self, cluster: str | None) -> Role:
        if cluster and self.cluster_roles:
            return self.cluster_roles.get(cluster, self.role)
        return self.role

    def has_role(self, required: Role, cluster: str | None = None) -> bool:
        return self.role_for(cluster).satisfies(required)


# The principal used when AUTH_MODE=none. Full rights, because the mode exists
# for local development where there is nothing to protect.
ANONYMOUS_ADMIN = Principal(username="anonymous", role=Role.ADMIN, provider="none")


def require_role(principal: Principal, required: Role, cluster: str | None = None) -> None:
    if not principal.has_role(required, cluster):
        actual = principal.role_for(cluster)
        where = f" on cluster {cluster!r}" if cluster else ""
        raise AuthorizationError(
            f"this action requires the {required} role{where}, "
            f"but {principal.username!r} has {actual}",
            required_role=required,
        )


def require_writable(
    principal: Principal,
    required: Role,
    *,
    cluster: str | None = None,
    global_read_only: bool,
    cluster_read_only: bool = False,
) -> None:
    """Gate a mutating action on both the read-only flags and the caller's role."""
    if global_read_only:
        raise ReadOnlyError(
            "this console is running in read-only mode (READ_ONLY=true); "
            "no write operations are permitted"
        )
    if cluster_read_only:
        raise ReadOnlyError(
            f"cluster {cluster!r} is configured read_only: true; "
            "no write operations are permitted against it"
        )
    require_role(principal, required, cluster)
