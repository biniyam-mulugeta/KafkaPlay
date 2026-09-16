"""Broker failure handling.

A cluster being unreachable is an expected operating condition, not an
exception the console should crash on. Every read path converts broker trouble
into a *degraded* result: HTTP 200 with a `degraded` block the UI renders as a
banner, so one sick cluster never takes down the page.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DegradedReason(StrEnum):
    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"
    AUTH_FAILED = "auth_failed"
    UNSUPPORTED = "unsupported"
    NOT_AUTHORIZED = "not_authorized"
    UNKNOWN = "unknown"


class Degraded(BaseModel):
    """Why a response is incomplete, in terms an operator can act on."""

    reason: DegradedReason
    message: str
    hint: str | None = Field(
        default=None,
        description="What the operator might do about it.",
    )


class KafkaGateError(Exception):
    """Base class for broker access failures."""

    reason: DegradedReason = DegradedReason.UNKNOWN
    hint: str | None = None

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if hint is not None:
            self.hint = hint

    def to_degraded(self) -> Degraded:
        return Degraded(reason=self.reason, message=self.message, hint=self.hint)


class BrokerUnreachableError(KafkaGateError):
    reason = DegradedReason.UNREACHABLE
    hint = (
        "Check bootstrap_servers, and that the brokers' advertised.listeners "
        "are resolvable from this container. See docs/connections.md."
    )


class BrokerTimeoutError(KafkaGateError):
    reason = DegradedReason.TIMEOUT
    hint = "The broker did not answer in time. Raise ADMIN_TIMEOUT_SECONDS if this persists."


class AuthenticationFailedError(KafkaGateError):
    reason = DegradedReason.AUTH_FAILED
    hint = "Check the SASL mechanism and credentials for this cluster."


class NotAuthorizedError(KafkaGateError):
    reason = DegradedReason.NOT_AUTHORIZED
    hint = "The configured principal lacks an ACL for this operation."


class UnsupportedOperationError(KafkaGateError):
    """The broker does not implement this API.

    Raised for Redpanda, Event Hubs and older clusters. The UI greys the
    feature out rather than offering a button that cannot work.
    """

    reason = DegradedReason.UNSUPPORTED
    hint = "This broker does not support the operation."


# librdkafka reports failures as error codes on a KafkaException. Mapping them
# here keeps confluent_kafka imports out of the API layer.
_TIMEOUT_CODES = frozenset({"_TIMED_OUT", "_TIMED_OUT_QUEUE", "REQUEST_TIMED_OUT"})
_UNREACHABLE_CODES = frozenset(
    {"_TRANSPORT", "_ALL_BROKERS_DOWN", "_RESOLVE", "BROKER_NOT_AVAILABLE"}
)
_AUTH_CODES = frozenset({"_AUTHENTICATION", "SASL_AUTHENTICATION_FAILED"})
_AUTHZ_CODES = frozenset(
    {"TOPIC_AUTHORIZATION_FAILED", "GROUP_AUTHORIZATION_FAILED", "CLUSTER_AUTHORIZATION_FAILED"}
)
_UNSUPPORTED_CODES = frozenset({"UNSUPPORTED_VERSION", "_UNSUPPORTED_FEATURE", "UNKNOWN"})


def translate_kafka_error(exc: BaseException) -> KafkaGateError:
    """Map a librdkafka exception onto a typed gate error."""
    if isinstance(exc, KafkaGateError):
        return exc

    name = ""
    # confluent_kafka.KafkaException wraps a KafkaError with .name().
    args = getattr(exc, "args", ())
    if args:
        candidate = args[0]
        name_getter = getattr(candidate, "name", None)
        if callable(name_getter):
            try:
                name = str(name_getter())
            except Exception:  # pragma: no cover - defensive
                name = ""

    message = str(exc) or name or exc.__class__.__name__

    if name in _TIMEOUT_CODES:
        return BrokerTimeoutError(message)
    if name in _UNREACHABLE_CODES:
        return BrokerUnreachableError(message)
    if name in _AUTH_CODES:
        return AuthenticationFailedError(message)
    if name in _AUTHZ_CODES:
        return NotAuthorizedError(message)
    if name in _UNSUPPORTED_CODES:
        return UnsupportedOperationError(message)

    lowered = message.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return BrokerTimeoutError(message)
    if "authentication" in lowered:
        return AuthenticationFailedError(message)
    if "resolve" in lowered or "connect" in lowered or "transport" in lowered:
        return BrokerUnreachableError(message)

    return KafkaGateError(message)
