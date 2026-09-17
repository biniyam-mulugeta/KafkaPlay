"""Application settings.

Twelve-factor: everything here comes from the environment (or an ``.env`` file
in development). Nothing in this module knows about any particular Kafka
cluster -- cluster definitions live in ``config/clusters.yaml``.
"""

from __future__ import annotations

import ipaddress
import secrets
from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthMode(StrEnum):
    LOCAL = "local"
    OIDC = "oidc"
    NONE = "none"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


_LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})


def _is_loopback(host: str) -> bool:
    """True when ``host`` can only be reached from the local machine."""
    candidate = host.strip().lower()
    if candidate in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _load_or_create_secret(path: Path) -> str:
    """Read the persisted session secret, creating it on first run.

    Owner-only permissions: anyone who can read this file can forge a session.
    """
    try:
        if path.exists():
            existing = path.read_text(encoding="utf-8").strip()
            if len(existing) >= 32:
                return existing
    except OSError:
        pass

    secret = secrets.token_urlsafe(32)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secret, encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        # A read-only volume is survivable: the console still works, but
        # sessions will not outlive a restart.
        pass
    return secret


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    # --- Identity & appearance ---------------------------------------------
    app_name: str = Field(default="Offsetscope", description="Product name shown in the UI.")
    theme: str = Field(default="offsetscope", description="Directory name under themes/.")
    themes_dir: Path = Field(default=Path("themes"))
    default_locale: str = Field(default="en")
    static_dir: Path = Field(
        default=Path("static"),
        description=(
            "Built frontend bundle. Absent during backend-only development, "
            "in which case the API is served without a UI."
        ),
    )

    # --- Serving ------------------------------------------------------------
    console_host: str = Field(default="127.0.0.1")
    console_port: int = Field(default=8080, ge=1, le=65535)
    root_path: str = Field(default="", description="Set when served under a reverse-proxy subpath.")

    # --- Safety -------------------------------------------------------------
    read_only: bool = Field(
        default=False,
        description="Global kill switch for every mutating Kafka operation.",
    )

    # --- Authentication -----------------------------------------------------
    auth_mode: AuthMode = Field(default=AuthMode.LOCAL)
    allow_insecure_no_auth: bool = Field(
        default=False,
        description=(
            "Required acknowledgement to run AUTH_MODE=none on a non-loopback bind. "
            "Inside Docker the bind is always 0.0.0.0, so container users must set this "
            "explicitly -- that is deliberate."
        ),
    )
    session_secret: str = Field(
        default="",
        description="Generated and persisted on first run when left unset.",
    )
    secret_file: Path = Field(
        default=Path("data/.session_secret"),
        description="Where a generated session secret is persisted.",
    )
    session_max_age_seconds: int = Field(default=60 * 60 * 12, ge=60)
    session_cookie_name: str = Field(default="offsetscope_session")
    csrf_cookie_name: str = Field(default="offsetscope_csrf")
    secure_cookies: bool = Field(
        default=False,
        description="Set true when serving over HTTPS so cookies carry the Secure flag.",
    )

    # Optional pre-seeded admin. When left blank, the first person to register
    # claims the admin account instead -- see allow_signup.
    admin_username: str = Field(default="admin")
    admin_password: str = Field(default="")

    allow_signup: bool = Field(
        default=False,
        description=(
            "Allow anyone who can reach the console to register an account. "
            "Registration is ALWAYS open while no users exist, so a fresh "
            "deployment can be claimed; that first account becomes the admin. "
            "Afterwards this must be turned on explicitly, and new accounts are "
            "created as viewers."
        ),
    )

    # --- OIDC (used when AUTH_MODE=oidc) ------------------------------------
    oidc_issuer_url: str | None = Field(default=None)
    oidc_client_id: str | None = Field(default=None)
    oidc_client_secret: str | None = Field(default=None)
    oidc_redirect_uri: str | None = Field(default=None)
    oidc_scopes: str = Field(default="openid profile email")
    oidc_username_claim: str = Field(default="preferred_username")
    oidc_role_claim: str = Field(
        default="groups",
        description="Claim holding the caller's groups or roles.",
    )
    oidc_admin_value: str | None = Field(
        default=None, description="Claim value that grants the admin role."
    )
    oidc_operator_value: str | None = Field(
        default=None, description="Claim value that grants the operator role."
    )

    # --- Storage ------------------------------------------------------------
    database_url: str = Field(default="sqlite:///./data/offsetscope.db")

    # --- Clusters -----------------------------------------------------------
    clusters_file: Path = Field(default=Path("config/clusters.yaml"))
    kafka_bootstrap_servers: str | None = Field(
        default=None,
        description=(
            "Shortcut for a single-cluster deployment: creates one cluster without "
            "a clusters.yaml. Clusters added in the UI are stored in the database."
        ),
    )
    kafka_cluster_name: str = Field(default="kafka")

    # --- Broker call budget -------------------------------------------------
    admin_timeout_seconds: float = Field(default=10.0, gt=0)
    admin_cache_ttl_seconds: float = Field(
        default=5.0,
        ge=0,
        description="Shared TTL cache so N browser tabs cost one broker call.",
    )
    admin_pool_size: int = Field(default=8, ge=1)

    # --- Built-in offset sampler -------------------------------------------
    sampler_enabled: bool = Field(default=True)
    sampler_interval_seconds: int = Field(default=30, ge=5)
    sampler_retention_days: int = Field(default=7, ge=1)
    sampler_max_partitions: int = Field(
        default=2000,
        ge=1,
        description=(
            "Above this partition count the sampler backs off to a longer interval "
            "rather than hammering a large production cluster."
        ),
    )

    # --- Optional Prometheus add-on ----------------------------------------
    prometheus_url: str | None = Field(default=None)

    # --- Privacy ------------------------------------------------------------
    masking_enabled: bool = Field(default=True)

    # --- Notifications (all optional, unconfigured by default) --------------
    webhook_url: str | None = Field(default=None)
    webhook_secret: str | None = Field(
        default=None,
        description="Signs the webhook body with HMAC-SHA256 so receivers can verify it.",
    )
    slack_webhook_url: str | None = Field(default=None)
    teams_webhook_url: str | None = Field(default=None)

    smtp_host: str | None = Field(default=None)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)
    smtp_from: str | None = Field(default=None)
    smtp_default_to: str | None = Field(default=None)
    smtp_starttls: bool = Field(default=True)

    alerts_enabled: bool = Field(default=True)
    alert_interval_seconds: int = Field(default=30, ge=5)

    # --- Logging ------------------------------------------------------------
    log_level: str = Field(default="INFO")
    log_format: LogFormat = Field(default=LogFormat.JSON)

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        level = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if level not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return level

    @model_validator(mode="after")
    def _guard_no_auth(self) -> Settings:
        """Refuse to start wide open unless the operator says so in writing."""
        if (
            self.auth_mode is AuthMode.NONE
            and not _is_loopback(self.console_host)
            and not self.allow_insecure_no_auth
        ):
            raise ValueError(
                f"AUTH_MODE=none is only permitted on a loopback bind, but "
                f"CONSOLE_HOST={self.console_host!r} is reachable from other hosts. "
                "Set ALLOW_INSECURE_NO_AUTH=true to acknowledge that this exposes "
                "every topic and admin action to anyone who can reach this port, "
                "or set AUTH_MODE=local."
            )
        return self

    @model_validator(mode="after")
    def _require_oidc_settings(self) -> Settings:
        """Fail at startup rather than at the first login attempt."""
        if self.auth_mode is AuthMode.OIDC:
            missing = [
                name
                for name, value in (
                    ("OIDC_ISSUER_URL", self.oidc_issuer_url),
                    ("OIDC_CLIENT_ID", self.oidc_client_id),
                    ("OIDC_REDIRECT_URI", self.oidc_redirect_uri),
                )
                if not value
            ]
            if missing:
                raise ValueError("AUTH_MODE=oidc requires " + ", ".join(missing) + " to be set.")
        return self

    @model_validator(mode="after")
    def _resolve_session_secret(self) -> Settings:
        """Use the configured secret, or generate and persist one.

        Refusing to start without SESSION_SECRET made a first run need manual
        setup for no security benefit: a generated secret is stronger than one
        a person invents. It is persisted next to the database so sessions
        survive a restart, and an operator can still pin it via the
        environment for multi-replica deployments, where every replica must
        share the same value.
        """
        if self.session_secret:
            if len(self.session_secret) < 32:
                raise ValueError("SESSION_SECRET must be at least 32 characters.")
            return self

        if self.auth_mode is AuthMode.NONE:
            # Nothing to keep logged in; an ephemeral secret is correct here.
            self.session_secret = secrets.token_urlsafe(32)
            return self

        self.session_secret = _load_or_create_secret(self.secret_file)
        return self

    @property
    def is_no_auth(self) -> bool:
        return self.auth_mode is AuthMode.NONE

    @property
    def theme_dir(self) -> Path:
        return self.themes_dir / self.theme


def load_settings(**overrides: object) -> Settings:
    """Build settings. Overrides exist so tests never touch the real environment."""
    return Settings(**overrides)  # type: ignore[arg-type]
