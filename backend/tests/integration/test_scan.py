"""Message scanning against a live broker."""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import Iterator

import pytest
from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

from app.clusters.models import ClusterConfig, MaskPreset, MaskRule
from app.codecs.decode import PayloadFormat
from app.search.scan import MessageScanner, ScanRequest, StartFrom, StopReason
from app.security.masking import Masker

pytestmark = pytest.mark.integration

TOTAL = 60
PARTITIONS = 3


@pytest.fixture
def scan_topic(bootstrap_servers: str) -> Iterator[str]:
    """Known messages: statuses, an IP, and one non-JSON record."""
    name = f"kafkaplay-scan-{uuid.uuid4().hex[:8]}"
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    admin.create_topics([NewTopic(name, num_partitions=PARTITIONS, replication_factor=1)])[
        name
    ].result(timeout=30)

    producer = Producer({"bootstrap.servers": bootstrap_servers})
    for i in range(TOTAL):
        producer.produce(
            name,
            key=f"cust-{i:03d}".encode(),
            value=json.dumps(
                {
                    "i": i,
                    "status": "failed" if i % 10 == 0 else "ok",
                    "amount_cents": i * 100,
                    "client_ip": "203.0.113.42",
                }
            ).encode(),
            headers=[("source", b"gateway")],
        )
    producer.produce(name, key=b"plain", value=b"not json at all")
    producer.flush(30)

    yield name

    with contextlib.suppress(Exception):
        admin.delete_topics([name])[name].result(timeout=30)


@pytest.fixture
def scanner(bootstrap_servers: str) -> MessageScanner:
    return MessageScanner(
        ClusterConfig(name="it", bootstrap_servers=bootstrap_servers), timeout_seconds=20.0
    )


def no_masking() -> Masker:
    return Masker([], enabled=False)


class TestScanning:
    async def test_reads_from_oldest(self, scanner: MessageScanner, scan_topic: str) -> None:
        result = await scanner.scan(
            ScanRequest(topic=scan_topic, start_from=StartFrom.OLDEST, max_results=500),
            masker=no_masking(),
        )
        assert len(result.messages) == TOTAL + 1
        assert result.stop_reason is StopReason.COMPLETED
        assert sorted(result.partitions_scanned) == list(range(PARTITIONS))

    async def test_decodes_json_and_text(self, scanner: MessageScanner, scan_topic: str) -> None:
        result = await scanner.scan(
            ScanRequest(topic=scan_topic, start_from=StartFrom.OLDEST, max_results=500),
            masker=no_masking(),
        )
        formats = {message.value.format for message in result.messages}
        assert PayloadFormat.JSON in formats
        assert PayloadFormat.TEXT in formats

    async def test_headers_are_returned(self, scanner: MessageScanner, scan_topic: str) -> None:
        result = await scanner.scan(
            ScanRequest(topic=scan_topic, start_from=StartFrom.OLDEST, max_results=500),
            masker=no_masking(),
        )
        with_headers = [m for m in result.messages if m.headers]
        assert with_headers
        assert with_headers[0].headers["source"] == "gateway"

    async def test_single_partition_scan(self, scanner: MessageScanner, scan_topic: str) -> None:
        result = await scanner.scan(
            ScanRequest(
                topic=scan_topic,
                partitions=[1],
                start_from=StartFrom.OLDEST,
                max_results=500,
            ),
            masker=no_masking(),
        )
        assert result.partitions_scanned == [1]
        assert all(message.partition == 1 for message in result.messages)

    async def test_start_from_offset(self, scanner: MessageScanner, scan_topic: str) -> None:
        result = await scanner.scan(
            ScanRequest(
                topic=scan_topic,
                partitions=[0],
                start_from=StartFrom.OFFSET,
                offset=2,
                max_results=500,
            ),
            masker=no_masking(),
        )
        if result.messages:
            assert min(message.offset for message in result.messages) >= 2


class TestFiltering:
    async def test_filter_narrows_results(self, scanner: MessageScanner, scan_topic: str) -> None:
        result = await scanner.scan(
            ScanRequest(
                topic=scan_topic,
                start_from=StartFrom.OLDEST,
                filter_expression="value.status == 'failed'",
                max_results=500,
            ),
            masker=no_masking(),
        )
        assert result.messages
        assert all(m.value.value["status"] == "failed" for m in result.messages)
        # Filtering happens after reading, so everything is still scanned.
        assert result.scanned > len(result.messages)

    async def test_numeric_filter(self, scanner: MessageScanner, scan_topic: str) -> None:
        result = await scanner.scan(
            ScanRequest(
                topic=scan_topic,
                start_from=StartFrom.OLDEST,
                filter_expression="value.amount_cents > `5000`",
                max_results=500,
            ),
            masker=no_masking(),
        )
        assert all(m.value.value["amount_cents"] > 5000 for m in result.messages)

    async def test_filter_skips_records_of_a_different_shape(
        self, scanner: MessageScanner, scan_topic: str
    ) -> None:
        # The plain-text record has no .status; it must be skipped, not crash.
        result = await scanner.scan(
            ScanRequest(
                topic=scan_topic,
                start_from=StartFrom.OLDEST,
                filter_expression="value.status == 'ok'",
                max_results=500,
            ),
            masker=no_masking(),
        )
        assert all(m.value.format is PayloadFormat.JSON for m in result.messages)


class TestBudgets:
    async def test_max_results_stops_the_scan(
        self, scanner: MessageScanner, scan_topic: str
    ) -> None:
        result = await scanner.scan(
            ScanRequest(topic=scan_topic, start_from=StartFrom.OLDEST, max_results=5),
            masker=no_masking(),
        )
        assert len(result.messages) == 5
        assert result.stop_reason is StopReason.MAX_RESULTS

    async def test_scanned_budget_stops_the_scan(
        self, scanner: MessageScanner, scan_topic: str
    ) -> None:
        result = await scanner.scan(
            ScanRequest(
                topic=scan_topic,
                start_from=StartFrom.OLDEST,
                max_results=500,
                max_scanned=10,
            ),
            masker=no_masking(),
        )
        assert result.stop_reason is StopReason.SCANNED_BUDGET
        assert result.scanned <= 11

    async def test_elapsed_time_is_reported(self, scanner: MessageScanner, scan_topic: str) -> None:
        result = await scanner.scan(
            ScanRequest(topic=scan_topic, start_from=StartFrom.OLDEST, max_results=10),
            masker=no_masking(),
        )
        assert result.elapsed_seconds >= 0


class TestMaskingDuringScan:
    async def test_ip_is_masked_in_results(self, scanner: MessageScanner, scan_topic: str) -> None:
        masker = Masker([MaskRule(preset=MaskPreset.IPV4)])
        result = await scanner.scan(
            ScanRequest(topic=scan_topic, start_from=StartFrom.OLDEST, max_results=10),
            masker=masker,
        )
        json_messages = [m for m in result.messages if m.value.format is PayloadFormat.JSON]
        assert json_messages
        for message in json_messages:
            assert message.value.value["client_ip"] == "203.0.113.xxx"
            assert message.masked

    async def test_filter_sees_unmasked_values(
        self, scanner: MessageScanner, scan_topic: str
    ) -> None:
        """Masking must not break filtering.

        The filter runs against the true payload and masking is applied only
        to what is returned, so an operator can still search for a real IP
        without ever receiving one.
        """
        result = await scanner.scan(
            ScanRequest(
                topic=scan_topic,
                start_from=StartFrom.OLDEST,
                filter_expression="value.client_ip == '203.0.113.42'",
                max_results=500,
            ),
            masker=Masker([MaskRule(preset=MaskPreset.IPV4)]),
        )
        assert result.messages, "filter should match on the unmasked value"
        assert all(m.value.value["client_ip"] == "203.0.113.xxx" for m in result.messages)


class TestScanIsolation:
    async def test_scanning_creates_no_consumer_group(
        self, scanner: MessageScanner, scan_topic: str, bootstrap_servers: str
    ) -> None:
        """A scan must be invisible to the group coordinator.

        Manual assignment with no commits means scanning never shows up as a
        consumer group, so it cannot be mistaken for a real consumer or
        disturb one.
        """
        admin = AdminClient({"bootstrap.servers": bootstrap_servers})
        before = {g.group_id for g in admin.list_consumer_groups(request_timeout=15).result().valid}

        await scanner.scan(
            ScanRequest(topic=scan_topic, start_from=StartFrom.OLDEST, max_results=50),
            masker=no_masking(),
        )

        after = {g.group_id for g in admin.list_consumer_groups(request_timeout=15).result().valid}
        new_groups = {g for g in after - before if g.startswith("kafkaplay-scan-")}
        assert not new_groups, f"scan leaked consumer groups: {new_groups}"
