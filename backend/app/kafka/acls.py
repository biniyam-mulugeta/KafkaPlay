"""ACL listing and management.

Many clusters have no authorizer configured at all, in which case the broker
answers with SECURITY_DISABLED rather than an empty list. That is a
configuration fact, not an error, so it is surfaced as a clear message instead
of an empty table that implies "no ACLs exist".
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from confluent_kafka.admin import (  # type: ignore[attr-defined]
    AclBinding,
    AclBindingFilter,
    AclOperation,
    AclPermissionType,
    ResourcePatternType,
    ResourceType,
)
from pydantic import BaseModel, Field

from app.kafka.errors import KafkaGateError, UnsupportedOperationError
from app.kafka.gate import KafkaGate
from app.kafka.models import Capability


class AclResourceType(StrEnum):
    ANY = "any"
    TOPIC = "topic"
    GROUP = "group"
    CLUSTER = "cluster"
    TRANSACTIONAL_ID = "transactional_id"


class AclPattern(StrEnum):
    ANY = "any"
    LITERAL = "literal"
    PREFIXED = "prefixed"


class AclModel(BaseModel):
    resource_type: str
    resource_name: str
    pattern_type: str
    principal: str
    host: str
    operation: str
    permission: str


class AclListResponse(BaseModel):
    acls: list[AclModel] = Field(default_factory=list)
    supported: bool = True
    message: str | None = None


_RESOURCE_TYPES = {
    AclResourceType.ANY: ResourceType.ANY,
    AclResourceType.TOPIC: ResourceType.TOPIC,
    AclResourceType.GROUP: ResourceType.GROUP,
    AclResourceType.CLUSTER: ResourceType.BROKER,
    AclResourceType.TRANSACTIONAL_ID: ResourceType.TRANSACTIONAL_ID,
}

_PATTERN_TYPES = {
    AclPattern.ANY: ResourcePatternType.ANY,
    AclPattern.LITERAL: ResourcePatternType.LITERAL,
    AclPattern.PREFIXED: ResourcePatternType.PREFIXED,
}


def _name(value: Any) -> str:
    return str(getattr(value, "name", value)).rsplit(".", 1)[-1]


def _to_model(binding: Any) -> AclModel:
    return AclModel(
        resource_type=_name(binding.restype),
        resource_name=str(binding.name),
        pattern_type=_name(binding.resource_pattern_type),
        principal=str(binding.principal),
        host=str(binding.host),
        operation=_name(binding.operation),
        permission=_name(binding.permission_type),
    )


class AclOps:
    def __init__(self, gate: KafkaGate) -> None:
        self._gate = gate

    async def list_acls(
        self,
        *,
        resource_type: AclResourceType = AclResourceType.ANY,
        resource_name: str | None = None,
        principal: str | None = None,
    ) -> AclListResponse:
        await self._gate.require(Capability.DESCRIBE_ACLS)
        admin = await self._gate._client()

        # The binding filter takes strings, not None; an empty string is how
        # librdkafka expresses "match any" for these fields.
        acl_filter = AclBindingFilter(
            _RESOURCE_TYPES[resource_type],
            resource_name or "",
            ResourcePatternType.ANY,
            principal or "",
            "",
            AclOperation.ANY,
            AclPermissionType.ANY,
        )

        def run() -> Any:
            future = admin.describe_acls(acl_filter, request_timeout=self._gate.timeout)
            return future.result(timeout=self._gate.timeout)

        try:
            bindings = await self._gate._run(run)
        except KafkaGateError as exc:
            lowered = exc.message.lower()
            # No authorizer configured is a configuration fact, not a failure.
            if "security_disabled" in lowered or "authorizer" in lowered:
                return AclListResponse(
                    acls=[],
                    supported=False,
                    message=(
                        "This cluster has no authorizer configured, so it has no ACLs. "
                        "Set authorizer.class.name on the brokers to use them."
                    ),
                )
            raise

        return AclListResponse(
            acls=sorted(
                (_to_model(binding) for binding in bindings),
                key=lambda acl: (acl.resource_type, acl.resource_name, acl.principal),
            )
        )

    async def create_acl(
        self,
        *,
        resource_type: AclResourceType,
        resource_name: str,
        pattern_type: AclPattern,
        principal: str,
        host: str,
        operation: str,
        permission: str,
    ) -> None:
        await self._gate.require(Capability.ALTER_ACLS)
        admin = await self._gate._client()

        try:
            binding = AclBinding(
                _RESOURCE_TYPES[resource_type],
                resource_name,
                _PATTERN_TYPES[pattern_type],
                principal,
                host,
                AclOperation[operation.upper()],
                AclPermissionType[permission.upper()],
            )
        except KeyError as exc:
            raise KafkaGateError(f"unknown ACL operation or permission: {exc}") from exc

        def run() -> None:
            futures = admin.create_acls([binding], request_timeout=self._gate.timeout)
            for future in futures.values():
                future.result(timeout=self._gate.timeout)

        await self._gate._run(run)

    async def delete_acl(
        self,
        *,
        resource_type: AclResourceType,
        resource_name: str,
        pattern_type: AclPattern,
        principal: str,
        host: str,
        operation: str,
        permission: str,
    ) -> int:
        await self._gate.require(Capability.ALTER_ACLS)
        admin = await self._gate._client()

        try:
            acl_filter = AclBindingFilter(
                _RESOURCE_TYPES[resource_type],
                resource_name,
                _PATTERN_TYPES[pattern_type],
                principal,
                host,
                AclOperation[operation.upper()],
                AclPermissionType[permission.upper()],
            )
        except KeyError as exc:
            raise KafkaGateError(f"unknown ACL operation or permission: {exc}") from exc

        def run() -> int:
            futures = admin.delete_acls([acl_filter], request_timeout=self._gate.timeout)
            removed = 0
            for future in futures.values():
                removed += len(future.result(timeout=self._gate.timeout))
            return removed

        return await self._gate._run(run)


def available_operations() -> list[str]:
    return sorted(op.name for op in AclOperation if op.name not in {"UNKNOWN", "ANY"})


def available_permissions() -> list[str]:
    return sorted(p.name for p in AclPermissionType if p.name not in {"UNKNOWN", "ANY"})


__all__ = [
    "AclListResponse",
    "AclModel",
    "AclOps",
    "AclPattern",
    "AclResourceType",
    "UnsupportedOperationError",
    "available_operations",
    "available_permissions",
]
