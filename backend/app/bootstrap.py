"""First-run setup: create the initial admin account.

Runs once against an empty user table. If ADMIN_PASSWORD is unset we generate
one and print it to the log exactly once, which is friendlier than refusing to
start and is safe because the log is the operator's own stdout.
"""

from __future__ import annotations

import secrets

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
        generated = False
        if not password:
            password = secrets.token_urlsafe(18)
            generated = True

        try:
            password_hash = hash_password(password)
        except PasswordError as exc:
            raise RuntimeError(
                f"ADMIN_PASSWORD is not usable: {exc}. "
                "Set a password of at least 12 characters, or leave ADMIN_PASSWORD "
                "unset to have one generated."
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

        if generated:
            # Printed once, never stored in plaintext, never logged again.
            log.warning(
                "generated_initial_admin_password",
                username=settings.admin_username,
                generated_password=password,
                hint="Store this now and set ADMIN_PASSWORD, or change it in the UI.",
            )
        else:
            log.info("created_initial_admin", username=settings.admin_username)
