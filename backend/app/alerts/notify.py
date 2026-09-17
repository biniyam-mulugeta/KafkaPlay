"""Notification delivery: webhook, Slack, Microsoft Teams, SMTP.

Every sink is optional and unconfigured by default. A delivery failure is
recorded against the firing and logged, but never propagated -- a broken
webhook must not stop alert evaluation.

The generic webhook is signed with HMAC-SHA256 over the exact request body, so
a receiver can verify the payload really came from this console.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

from app.config import Settings
from app.logging import get_logger
from app.store.models import AlertFiring, AlertSeverity, AlertState

log = get_logger(__name__)

SIGNATURE_HEADER = "X-Offsetscope-Signature"

_SEVERITY_COLOURS = {
    AlertSeverity.INFO: "#1b5e9e",
    AlertSeverity.WARNING: "#b26a00",
    AlertSeverity.CRITICAL: "#b3261e",
}


def _payload(firing: AlertFiring, app_name: str) -> dict[str, Any]:
    return {
        "source": app_name,
        "rule": firing.rule_name,
        "cluster": firing.cluster,
        "severity": str(firing.severity),
        "state": str(firing.state),
        "value": firing.value,
        "message": firing.message,
        "at": firing.at.isoformat(),
    }


def sign(body: bytes, secret: str) -> str:
    """HMAC-SHA256 of the exact bytes sent, hex encoded."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _headline(firing: AlertFiring, app_name: str) -> str:
    verb = "RESOLVED" if firing.state is AlertState.OK else str(firing.severity).upper()
    return f"[{verb}] {firing.rule_name} · {firing.cluster}"


class Notifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def any_configured(self) -> bool:
        s = self._settings
        return bool(s.webhook_url or s.slack_webhook_url or s.teams_webhook_url or s.smtp_host)

    async def dispatch(self, firings: list[AlertFiring]) -> None:
        for firing in firings:
            errors: list[str] = []
            delivered = False

            for send in (self._send_webhook, self._send_slack, self._send_teams):
                try:
                    if await send(firing):
                        delivered = True
                except Exception as exc:
                    errors.append(f"{send.__name__}: {exc}")

            try:
                if await self._send_email(firing):
                    delivered = True
            except Exception as exc:
                errors.append(f"email: {exc}")

            firing.notified = delivered
            firing.notify_error = "; ".join(errors)[:1000] or None
            if errors:
                log.warning("alert_notify_failed", rule=firing.rule_name, errors=errors)

    async def _send_webhook(self, firing: AlertFiring) -> bool:
        url = self._settings.webhook_url
        if not url:
            return False
        body = json.dumps(_payload(firing, self._settings.app_name)).encode()
        headers = {"Content-Type": "application/json"}
        if self._settings.webhook_secret:
            headers[SIGNATURE_HEADER] = sign(body, self._settings.webhook_secret)

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
        return True

    async def _send_slack(self, firing: AlertFiring) -> bool:
        url = self._settings.slack_webhook_url
        if not url:
            return False
        colour = "#1b7f4b" if firing.state is AlertState.OK else _SEVERITY_COLOURS[firing.severity]
        body = {
            "text": _headline(firing, self._settings.app_name),
            "attachments": [
                {
                    "color": colour,
                    "fields": [
                        {"title": "Cluster", "value": firing.cluster, "short": True},
                        {"title": "Severity", "value": str(firing.severity), "short": True},
                        {"title": "Detail", "value": firing.message, "short": False},
                    ],
                }
            ],
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
        return True

    async def _send_teams(self, firing: AlertFiring) -> bool:
        url = self._settings.teams_webhook_url
        if not url:
            return False
        colour = (
            "1b7f4b" if firing.state is AlertState.OK else _SEVERITY_COLOURS[firing.severity][1:]
        )
        body = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "themeColor": colour,
            "summary": _headline(firing, self._settings.app_name),
            "title": _headline(firing, self._settings.app_name),
            "sections": [
                {
                    "facts": [
                        {"name": "Cluster", "value": firing.cluster},
                        {"name": "Severity", "value": str(firing.severity)},
                        {"name": "Detail", "value": firing.message},
                    ]
                }
            ],
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
        return True

    async def _send_email(self, firing: AlertFiring) -> bool:
        s = self._settings
        if not s.smtp_host or not s.smtp_from:
            return False

        # Rules carry their own recipient; without one there is nowhere to send.
        recipient = getattr(firing, "_recipient", None) or s.smtp_default_to
        if not recipient:
            return False

        message = EmailMessage()
        message["Subject"] = _headline(firing, s.app_name)
        message["From"] = s.smtp_from
        message["To"] = recipient
        message.set_content(
            f"{firing.message}\n\n"
            f"Rule:     {firing.rule_name}\n"
            f"Cluster:  {firing.cluster}\n"
            f"Severity: {firing.severity}\n"
            f"State:    {firing.state}\n"
            f"Value:    {firing.value}\n"
            f"At:       {firing.at.isoformat()}\n"
        )

        host = s.smtp_host

        def send() -> None:
            with smtplib.SMTP(host, s.smtp_port, timeout=15) as server:
                if s.smtp_starttls:
                    server.starttls()
                if s.smtp_username and s.smtp_password:
                    server.login(s.smtp_username, s.smtp_password)
                server.send_message(message)

        # smtplib blocks, so keep it off the event loop.
        await asyncio.get_running_loop().run_in_executor(None, send)
        return True

    async def send_test(self, firing: AlertFiring) -> dict[str, Any]:
        """Deliver one notification and report per-sink outcomes."""
        results: dict[str, Any] = {}
        for name, send in (
            ("webhook", self._send_webhook),
            ("slack", self._send_slack),
            ("teams", self._send_teams),
            ("email", self._send_email),
        ):
            try:
                results[name] = "sent" if await send(firing) else "not configured"
            except Exception as exc:
                results[name] = f"failed: {exc}"
        return results
