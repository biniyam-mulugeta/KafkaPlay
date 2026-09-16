"""Login, logout, and the current-user endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.deps import DbDep, PrincipalDep, SettingsDep, get_session_codec
from app.auth.passwords import PasswordError, hash_password, verify_password
from app.auth.sessions import SessionCodec, SessionData, new_csrf_token
from app.config import AuthMode, Settings
from app.store.models import AuditEntry, AuditResult, AuthProvider, Role, User, utcnow

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class MeResponse(BaseModel):
    username: str
    role: Role
    provider: str
    csrf_token: str


def _set_session_cookie(
    response: Response, settings: SettingsDep, codec: SessionCodec, data: SessionData
) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=codec.dumps(data),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=MeResponse, summary="Log in with a local account")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    db: DbDep,
    codec: Annotated[SessionCodec, Depends(get_session_codec)],
) -> MeResponse:
    if settings.is_no_auth:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="this console is running with AUTH_MODE=none; there is nothing to log in to",
        )

    user = db.exec(select(User).where(User.username == payload.username)).first()
    # verify_password runs a dummy comparison for unknown users so timing does
    # not reveal whether an account exists.
    ok = verify_password(payload.password, user.password_hash if user else None)

    if not ok or user is None or not user.is_active:
        db.add(
            AuditEntry(
                username=payload.username,
                role=Role.VIEWER,
                action="auth.login",
                result=AuditResult.DENIED,
                source_ip=request.client.host if request.client else None,
                detail="invalid credentials or inactive account",
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
        )

    session = SessionData(
        username=user.username,
        role=str(user.role),
        provider=str(user.provider),
        csrf_token=new_csrf_token(),
    )
    _set_session_cookie(response, settings, codec, session)

    user.last_login_at = utcnow()
    db.add(user)
    db.add(
        AuditEntry(
            username=user.username,
            role=user.role,
            action="auth.login",
            result=AuditResult.SUCCESS,
            source_ip=request.client.host if request.client else None,
        )
    )
    db.commit()

    return MeResponse(
        username=user.username,
        role=user.role,
        provider=str(user.provider),
        csrf_token=session.csrf_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Clear the session")
def logout(response: Response, settings: SettingsDep) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )


@router.get("/me", response_model=MeResponse, summary="The authenticated caller")
def me(
    request: Request,
    principal: PrincipalDep,
    settings: SettingsDep,
    codec: Annotated[SessionCodec, Depends(get_session_codec)],
) -> MeResponse:
    csrf = ""
    if not settings.is_no_auth:
        token = request.cookies.get(settings.session_cookie_name)
        data = codec.loads(token) if token else None
        csrf = data.csrf_token if data else ""
    return MeResponse(
        username=principal.username,
        role=principal.role,
        provider=principal.provider,
        csrf_token=csrf,
    )


class SignupRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._@-]+$")
    password: str = Field(min_length=12, max_length=256)


class SignupAvailability(BaseModel):
    available: bool
    first_user: bool
    """True when no account exists yet, so this registration claims the admin."""

    reason: str | None = None


def _user_count(db: Session) -> int:
    return len(db.exec(select(User)).all())


def signup_availability(db: Session, settings: Settings) -> SignupAvailability:
    """Decide whether registration is open, and why.

    Open while the database has no users, so a fresh deployment can be claimed
    with no configuration. After that it stays closed unless an operator turns
    ALLOW_SIGNUP on -- otherwise anyone who could reach the port could create
    an account on a console wired to a production cluster.
    """
    if settings.auth_mode is not AuthMode.LOCAL:
        return SignupAvailability(
            available=False,
            first_user=False,
            reason=f"this deployment authenticates with {settings.auth_mode}",
        )

    if _user_count(db) == 0:
        return SignupAvailability(available=True, first_user=True)

    if settings.allow_signup:
        return SignupAvailability(available=True, first_user=False)

    return SignupAvailability(
        available=False,
        first_user=False,
        reason="registration is closed; an administrator can create accounts in Settings",
    )


@router.get("/signup", response_model=SignupAvailability, summary="Whether registration is open")
def can_signup(db: DbDep, settings: SettingsDep) -> SignupAvailability:
    return signup_availability(db, settings)


@router.post("/signup", response_model=MeResponse, status_code=201, summary="Register")
def signup(
    payload: SignupRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    db: DbDep,
    codec: Annotated[SessionCodec, Depends(get_session_codec)],
) -> MeResponse:
    availability = signup_availability(db, settings)
    if not availability.available:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=availability.reason or "registration is not available",
        )

    existing = db.exec(select(User).where(User.username == payload.username)).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that username is taken",
        )

    try:
        password_hash = hash_password(payload.password)
    except PasswordError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # The very first account administers the deployment; later ones start as
    # viewers and an admin promotes them.
    role = Role.ADMIN if availability.first_user else Role.VIEWER

    user = User(
        username=payload.username,
        password_hash=password_hash,
        provider=AuthProvider.LOCAL,
        role=role,
        last_login_at=utcnow(),
    )
    db.add(user)
    db.add(
        AuditEntry(
            username=payload.username,
            role=role,
            action="auth.signup",
            result=AuditResult.SUCCESS,
            source_ip=request.client.host if request.client else None,
            detail="claimed the first account" if availability.first_user else "self-registered",
        )
    )
    db.commit()
    db.refresh(user)

    session = SessionData(
        username=user.username,
        role=str(user.role),
        provider=str(user.provider),
        csrf_token=new_csrf_token(),
    )
    _set_session_cookie(response, settings, codec, session)

    return MeResponse(
        username=user.username,
        role=user.role,
        provider=str(user.provider),
        csrf_token=session.csrf_token,
    )
