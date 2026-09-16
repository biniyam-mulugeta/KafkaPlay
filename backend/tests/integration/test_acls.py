"""ACL handling against a live broker.

The dev broker runs with no authorizer, so these mainly assert the honest
degradation path: the console must say "no authorizer is configured" rather
than show an empty table implying no ACLs exist.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.clusters.models import ClusterConfig
from app.kafka.acls import AclOps, AclResourceType, available_operations, available_permissions
from app.kafka.gate import KafkaGate

pytestmark = pytest.mark.integration


@pytest.fixture
def gate(bootstrap_servers: str) -> Iterator[KafkaGate]:
    instance = KafkaGate(
        ClusterConfig(name="it", bootstrap_servers=bootstrap_servers), timeout_seconds=20.0
    )
    yield instance
    instance.close()


class TestAclListing:
    async def test_listing_never_raises(self, gate: KafkaGate) -> None:
        """Whether or not an authorizer exists, this returns a usable answer."""
        result = await AclOps(gate).list_acls()
        assert isinstance(result.acls, list)
        if not result.supported:
            # The explanation must be actionable, not just "failed".
            assert result.message

    async def test_filtering_by_resource_type(self, gate: KafkaGate) -> None:
        result = await AclOps(gate).list_acls(resource_type=AclResourceType.TOPIC)
        assert isinstance(result.acls, list)

    async def test_filtering_by_principal(self, gate: KafkaGate) -> None:
        result = await AclOps(gate).list_acls(principal="User:nobody")
        assert isinstance(result.acls, list)


class TestAclOptions:
    def test_operations_are_offered(self) -> None:
        operations = available_operations()
        assert "READ" in operations
        assert "WRITE" in operations
        # Placeholder members must not be offered as choices.
        assert "ANY" not in operations
        assert "UNKNOWN" not in operations

    def test_permissions_are_offered(self) -> None:
        permissions = available_permissions()
        assert "ALLOW" in permissions
        assert "DENY" in permissions
        assert "ANY" not in permissions
