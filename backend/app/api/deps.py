"""Shared request dependencies: settings, database, principal, CSRF."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, select

from app.auth.rbac import ANONYMOUS_ADMIN, Principal
from app.auth.sessions import CSRF_HEADER, SAFE_METHODS, SessionCodec, csrf_matches
from app.clusters.registry import ClusterRegistry, UnknownClusterError
from app.config import Settings
from app.kafka.gates import GateRegistry
from app.store.models import Role, User


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_registry(request: Request) -> ClusterRegistry:
    registry: ClusterRegistry = request.app.state.registry
    return registry


def get_session_codec(request: Request) -> SessionCodec:
    codec: SessionCodec = request.app.state.session_codec
    return codec


def get_gates(request: Request) -> GateRegistry:
    gates: GateRegistry = request.app.state.gates
    return gates


def get_db(request: Request) -> Iterator[Session]:
    session = Session(request.app.state.engine)
    try:
        yield session
    finally:
        session.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
RegistryDep = Annotated[ClusterRegistry, Depends(get_registry)]
DbDep = Annotated[Session, Depends(get_db)]
GatesDep = Annotated[GateRegistry, Depends(get_gates)]


def get_principal(
    request: Request,
    settings: SettingsDep,
    db: DbDep,
    codec: Annotated[SessionCodec, Depends(get_session_codec)],
) -> Principal:
    """Resolve the caller, or raise 401.

    In AUTH_MODE=none every caller is an admin. That is the whole point of the
    mode, and config.py refuses to enable it on a non-loopback bind without an
    explicit acknowledgement.
    """
    if settings.is_no_auth:
        return ANONYMOUS_ADMIN

    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Cookie"},
        )

    data = codec.loads(token)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="session is invalid or has expired",
        )

    # Re-read the user so a role change or deactivation takes effect
    # immediately rather than at the next login.
    user = db.exec(select(User).where(User.username == data.username)).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="account no longer active",
        )

    # CSRF: double-submit. The signed cookie holds the expected token and the
    # browser must echo it in a header, which a cross-site form cannot do.
    if request.method not in SAFE_METHODS:
        provided = request.headers.get(CSRF_HEADER)
        if not csrf_matches(data.csrf_token, provided):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing or invalid {CSRF_HEADER} header",
            )

    return Principal(username=user.username, role=user.role, provider=user.provider)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_admin(principal: PrincipalDep) -> Principal:
    if not principal.has_role(Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"this action requires the admin role; you have {principal.role}",
        )
    return principal


AdminDep = Annotated[Principal, Depends(require_admin)]


def resolve_cluster(
    cluster: str,
    registry: RegistryDep,
    # Depending on the principal here forces authentication to resolve BEFORE
    # the cluster lookup. Without it, FastAPI may run this first and answer
    # 404 for an unknown cluster but 401 for a real one, letting an
    # unauthenticated caller enumerate configured cluster names.
    _principal: PrincipalDep,
) -> str:
    """Validate the {cluster} path parameter, returning its name.

    The argument name must match the path parameter exactly, or FastAPI treats
    it as a required query parameter and every route 422s.
    """
    try:
        registry.get(cluster)
    except UnknownClusterError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return cluster
