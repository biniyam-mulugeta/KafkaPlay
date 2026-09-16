"""Integration tests against a real broker.

These run in CI across Kafka 3.9, Kafka 4.x and Redpanda. Locally they skip
unless KAFKAPLAY_TEST_BOOTSTRAP points at a broker, so `make test` stays green
for contributors with nothing running.

The point of this module in M1 is to prove the connection path and capability
detection work on every broker in the matrix. Topic and group features arrive
in M2.
"""

from __future__ import annotations

import uuid

import pytest
from confluent_kafka.admin import AdminClient, NewTopic

from app.clusters.models import ClusterConfig, SecurityProtocol

pytestmark = pytest.mark.integration


@pytest.fixture
def admin(bootstrap_servers: str) -> AdminClient:
    return AdminClient({"bootstrap.servers": bootstrap_servers, "client.id": "kafkaplay-tests"})


def test_cluster_config_accepts_a_real_broker(bootstrap_servers: str) -> None:
    cluster = ClusterConfig(name="test", bootstrap_servers=bootstrap_servers)
    assert cluster.security_protocol is SecurityProtocol.PLAINTEXT
    assert cluster.display_name == "test"


def test_metadata_lists_at_least_one_broker(admin: AdminClient) -> None:
    metadata = admin.list_topics(timeout=15)
    assert len(metadata.brokers) >= 1


def test_create_describe_and_delete_a_topic(admin: AdminClient) -> None:
    name = f"kafkaplay-it-{uuid.uuid4().hex[:8]}"

    created = admin.create_topics([NewTopic(name, num_partitions=2, replication_factor=1)])
    created[name].result(timeout=30)

    metadata = admin.list_topics(topic=name, timeout=15)
    assert name in metadata.topics
    assert len(metadata.topics[name].partitions) == 2

    deleted = admin.delete_topics([name])
    deleted[name].result(timeout=30)


def test_consumer_group_listing_is_supported(admin: AdminClient) -> None:
    """Redpanda and older brokers differ here; the console must not assume."""
    future = admin.list_consumer_groups(request_timeout=15)
    result = future.result()
    # An empty list is a perfectly valid answer; we are asserting the API
    # exists and returns a well-formed result, not that groups are present.
    assert hasattr(result, "valid")
