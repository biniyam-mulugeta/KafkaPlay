"""Local user management. Admin only, and every change is audited."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.deps import AdminDep, DbDep, PrincipalDep
from app.auth.passwords import PasswordError, hash_password, verify_password
from app.security.audit import audited, record_denial
from app.store.models import AuthProvider, Role, User

router = APIRouter(prefix="/users", tags=["users"])


class UserModel(BaseModel):
    id: int
    username: str
    role: Role
    provider: AuthProvider
    email: str | None
    display_name: str | None
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class UserListResponse(BaseModel):
    users: list[UserModel]


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._@-]+$")
    password: str = Field(min_length=12, max_length=256)
    role: Role = Role.VIEWER
    email: str | None = None
    display_name: str | None = None


class UpdateUserRequest(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    email: str | None = None
    display_name: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str | None = Field(
        default=None, description="Required when changing your own password."
    )
    new_password: str = Field(min_length=12, max_length=256)


@router.get("", response_model=UserListResponse, summary="List users")
async def list_users(_admin: AdminDep, db: DbDep) -> UserListResponse:
    rows = db.exec(select(User).order_by(col(User.username))).all()
    return UserListResponse(
        users=[UserModel.model_validate(row, from_attributes=True) for row in rows]
    )


@router.post("", response_model=UserModel, status_code=201, summary="Create a user")
async def create_user(
    request: Request,
    payload: CreateUserRequest,
    admin: AdminDep,
    db: DbDep,
) -> UserModel:
    existing = db.exec(select(User).where(User.username == payload.username)).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a user named {payload.username!r} already exists",
        )

    try:
        password_hash = hash_password(payload.password)
    except PasswordError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    user = User(
        username=payload.username,
        password_hash=password_hash,
        provider=AuthProvider.LOCAL,
        role=payload.role,
        email=payload.email,
        display_name=payload.display_name,
    )

    with audited(
        request.app.state.engine,
        principal=admin,
        action="user.create",
        target=payload.username,
        source_ip=request.client.host if request.client else None,
    ) as context:
        db.add(user)
        db.commit()
        db.refresh(user)
        # The password is never recorded, only the role it was granted.
        context["after"] = {"role": str(payload.role)}

    return UserModel.model_validate(user, from_attributes=True)


@router.patch("/{username}", response_model=UserModel, summary="Update a user")
async def update_user(
    request: Request,
    username: str,
    payload: UpdateUserRequest,
    admin: AdminDep,
    db: DbDep,
) -> UserModel:
    user = db.exec(select(User).where(User.username == username)).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such user")

    # Guard against an admin removing their own last route back in.
    if user.username == admin.username and (
        payload.role is not None and payload.role is not Role.ADMIN
    ):
        reason = "an administrator cannot demote their own account"
        record_denial(
            request.app.state.engine,
            principal=admin,
            action="user.update",
            reason=reason,
            target=username,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    if user.username == admin.username and payload.is_active is False:
        reason = "an administrator cannot deactivate their own account"
        record_denial(
            request.app.state.engine,
            principal=admin,
            action="user.update",
            reason=reason,
            target=username,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    before = {"role": str(user.role), "is_active": user.is_active}

    with audited(
        request.app.state.engine,
        principal=admin,
        action="user.update",
        target=username,
        before=before,
        source_ip=request.client.host if request.client else None,
    ) as context:
        if payload.role is not None:
            user.role = payload.role
        if payload.is_active is not None:
            user.is_active = payload.is_active
        if payload.email is not None:
            user.email = payload.email
        if payload.display_name is not None:
            user.display_name = payload.display_name
        db.add(user)
        db.commit()
        db.refresh(user)
        context["after"] = {"role": str(user.role), "is_active": user.is_active}

    return UserModel.model_validate(user, from_attributes=True)


@router.delete("/{username}", status_code=204, summary="Delete a user")
async def delete_user(request: Request, username: str, admin: AdminDep, db: DbDep) -> None:
    user = db.exec(select(User).where(User.username == username)).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such user")

    if user.username == admin.username:
        reason = "an administrator cannot delete their own account"
        record_denial(
            request.app.state.engine,
            principal=admin,
            action="user.delete",
            reason=reason,
            target=username,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    remaining_admins = len(
        [
            row
            for row in db.exec(select(User).where(User.role == Role.ADMIN)).all()
            if row.is_active and row.username != username
        ]
    )
    if user.role is Role.ADMIN and remaining_admins == 0:
        reason = "this is the last active administrator"
        record_denial(
            request.app.state.engine,
            principal=admin,
            action="user.delete",
            reason=reason,
            target=username,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    with audited(
        request.app.state.engine,
        principal=admin,
        action="user.delete",
        target=username,
        before={"role": str(user.role)},
        source_ip=request.client.host if request.client else None,
    ):
        db.delete(user)
        db.commit()


@router.post("/{username}/password", status_code=204, summary="Change a password")
async def change_password(
    request: Request,
    username: str,
    payload: ChangePasswordRequest,
    principal: PrincipalDep,
    db: DbDep,
) -> None:
    """Change your own password, or any password as an admin."""
    is_self = principal.username == username
    if not is_self and principal.role is not Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only an administrator can change another user's password",
        )

    user = db.exec(select(User).where(User.username == username)).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such user")

    # Changing your own password requires proving you know the current one, so
    # a borrowed session cannot lock the real owner out.
    if is_self and not verify_password(payload.current_password or "", user.password_hash):
        record_denial(
            request.app.state.engine,
            principal=principal,
            action="user.password",
            reason="current password did not match",
            target=username,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="current password is incorrect"
        )

    try:
        new_hash = hash_password(payload.new_password)
    except PasswordError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    with audited(
        request.app.state.engine,
        principal=principal,
        action="user.password",
        target=username,
        source_ip=request.client.host if request.client else None,
    ) as context:
        user.password_hash = new_hash
        db.add(user)
        db.commit()
        context["detail"] = "self-service" if is_self else "changed by an administrator"


RoleListResponse = Annotated[list[str], None]


@router.get("/roles/available", summary="The roles this deployment supports")
async def list_roles(_principal: PrincipalDep) -> dict[str, list[dict[str, str]]]:
    return {
        "roles": [
            {"name": str(Role.VIEWER), "description": "Read topics, groups, configs and metrics."},
            {
                "name": str(Role.OPERATOR),
                "description": "The above, plus produce, replay and reset offsets.",
            },
            {
                "name": str(Role.ADMIN),
                "description": "The above, plus topic, ACL and user management.",
            },
        ]
    }
