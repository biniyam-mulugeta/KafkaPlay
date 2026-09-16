"""First-run setup: create the initial admin account.

Runs once against an empty user table.

When ADMIN_PASSWORD is set, that admin is created up front. When it is not,
nothing is created and the first person to register claims the admin account
-- which is what makes a zero-configuration deployment usable.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlmodel import select

from app.auth.passwords import PasswordError, hash_password
from app.config import AuthMode, Settings
from app.logging import get_logger
from app.store.models import AuthProvider, Role, User
from app.store.session import session_scope

log = get_logger(__name__)


def ensure_first_admin(engine: Engine, settings: Settings) -> None:
    """Create the bootstrap admin when no users exist."""
    if settings.auth_mode is AuthMode.NONE:
        return

    with session_scope(engine) as session:
        existing = session.exec(select(User).limit(1)).first()
        if existing is not None:
            return

        password = settings.admin_password
        if not password:
            # No pre-seeded admin: the first person to register claims the
            # account. This keeps a fresh deployment usable with no
            # configuration at all, and avoids a printed password that nobody
            # reads. See POST /api/v1/auth/signup.
            log.info(
                "awaiting_first_registration",
                detail=(
                    "No users exist yet. The first account registered becomes the administrator."
                ),
            )
            return

        try:
            password_hash = hash_password(password)
        except PasswordError as exc:
            raise RuntimeError(
                f"ADMIN_PASSWORD is not usable: {exc}. "
                "Set a password of at least 12 characters, or leave ADMIN_PASSWORD "
                "unset and register the first account in the UI instead."
            ) from exc

        session.add(
            User(
                username=settings.admin_username,
                password_hash=password_hash,
                provider=AuthProvider.LOCAL,
                role=Role.ADMIN,
                display_name="Administrator",
            )
        )

        log.info("created_initial_admin", username=settings.admin_username)
