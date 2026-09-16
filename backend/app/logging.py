"""Structured logging to stdout.

JSON by default because this runs in a container and something else will be
collecting the stream. ``LOG_FORMAT=console`` gives readable output in dev.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.config import LogFormat, Settings

# Fields that must never reach the log stream, whatever a caller passes.
# Message payloads are excluded structurally (we never log them), but
# credentials can arrive via config echoes and exception context.
_REDACTED_KEYS = frozenset(
    {
        "password",
        "sasl_password",
        "session_secret",
        "admin_password",
        "ssl_key_password",
        "client_secret",
        "authorization",
        "cookie",
        "token",
        "access_token",
        "refresh_token",
    }
)

_REDACTED = "***redacted***"


def _redact(
    _logger: Any, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    for key in list(event_dict):
        if key.lower() in _REDACTED_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )
    # uvicorn installs its own handlers; let everything flow through the root.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True

    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _redact,
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format is LogFormat.JSON
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)
