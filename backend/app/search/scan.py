"""Bounded, cancellable message scans.

The rules that keep this safe to point at production:

* A scan only runs when a user starts one. Nothing polls messages.
* Every scan has a budget -- a maximum number of messages examined AND a
  maximum duration. Whichever is hit first ends the scan, and the response
  says which, so an empty result is never ambiguous.
* The consumer uses manual partition assignment with no group id, so scanning
  never joins a consumer group, never commits offsets, and is invisible to
  the group coordinator.
* The consumer is always closed, including on cancellation.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from confluent_kafka import Consumer, TopicPartition

from app.clusters.models import ClusterConfig
from app.codecs.decode import DecodedPayload, PayloadFormat, decode_payload
from app.kafka.errors import KafkaGateError, translate_kafka_error
from app.kafka.gate import build_client_config
from app.logging import get_logger
from app.search.dsl import MessageFilter
from app.security.masking import Masker

log = get_logger(__name__)


class StartFrom(StrEnum):
    NEWEST = "newest"
    OLDEST = "oldest"
    OFFSET = "offset"
    TIMESTAMP = "timestamp"


class StopReason(StrEnum):
    COMPLETED = "completed"
    MAX_RESULTS = "max_results"
    SCANNED_BUDGET = "scanned_budget"
    TIME_BUDGET = "time_budget"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(slots=True)
class ScanRequest:
    topic: str
    partitions: list[int] | None = None
    start_from: StartFrom = StartFrom.NEWEST
    offset: int | None = None
    timestamp_ms: int | None = None
    filter_expression: str | None = None
    max_results: int = 100
    max_scanned: int = 50_000
    max_seconds: float = 20.0


@dataclass(slots=True)
class ScannedMessage:
    topic: str
    partition: int
    offset: int
    timestamp: int | None
    timestamp_type: str | None
    key: DecodedPayload
    value: DecodedPayload
    headers: dict[str, str] = field(default_factory=dict)
    masked: bool = False


@dataclass(slots=True)
class ScanResult:
    messages: list[ScannedMessage]
    scanned: int
    elapsed_seconds: float
    stop_reason: StopReason
    partitions_scanned: list[int]
    error: str | None = None


def _headers_to_dict(raw: Any) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in raw or []:
        if isinstance(value, bytes):
            try:
                headers[name] = value.decode("utf-8")
            except UnicodeDecodeError:
                headers[name] = value.hex()
        else:
            headers[name] = "" if value is None else str(value)
    return headers


def _record_for_filter(message: ScannedMessage) -> dict[str, Any]:
    return {
        "key": message.key.value,
        "value": message.value.value,
        "headers": message.headers,
        "topic": message.topic,
        "partition": message.partition,
        "offset": message.offset,
        "timestamp": message.timestamp,
    }


class MessageScanner:
    """Runs one scan against one cluster."""

    def __init__(
        self,
        cluster: ClusterConfig,
        *,
        timeout_seconds: float = 10.0,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self._cluster = cluster
        self._timeout = timeout_seconds
        self._executor = executor

    def _build_consumer(self) -> Consumer:
        config = build_client_config(self._cluster, self._timeout)
        config.update(
            {
                # No group.id would be rejected by librdkafka, but because we
                # assign partitions manually and never commit, this group is
                # never created on the broker.
                "group.id": f"offsetscope-scan-{int(time.time() * 1000)}",
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
                "enable.partition.eof": True,
            }
        )
        return Consumer(config)

    def _assign(self, consumer: Consumer, request: ScanRequest) -> list[TopicPartition]:
        metadata = consumer.list_topics(topic=request.topic, timeout=self._timeout)
        topic_meta = metadata.topics.get(request.topic)
        if topic_meta is None or not topic_meta.partitions:
            raise KafkaGateError(f"topic {request.topic!r} does not exist")

        wanted = (
            sorted(topic_meta.partitions)
            if request.partitions is None
            else [p for p in sorted(topic_meta.partitions) if p in set(request.partitions)]
        )
        if not wanted:
            raise KafkaGateError("no matching partitions for this scan")

        assignments: list[TopicPartition] = []

        if request.start_from is StartFrom.TIMESTAMP and request.timestamp_ms is not None:
            probes = [TopicPartition(request.topic, p, request.timestamp_ms) for p in wanted]
            resolved = consumer.offsets_for_times(probes, timeout=self._timeout)
            for tp in resolved:
                low, high = consumer.get_watermark_offsets(
                    TopicPartition(request.topic, tp.partition), timeout=self._timeout
                )
                # A timestamp after the last message resolves to -1; start at
                # the end rather than replaying the whole partition.
                start = tp.offset if tp.offset is not None and tp.offset >= 0 else high
                assignments.append(TopicPartition(request.topic, tp.partition, start))
            return assignments

        for partition in wanted:
            low, high = consumer.get_watermark_offsets(
                TopicPartition(request.topic, partition), timeout=self._timeout
            )
            match request.start_from:
                case StartFrom.OLDEST:
                    start = low
                case StartFrom.OFFSET:
                    requested = request.offset if request.offset is not None else low
                    start = max(low, min(requested, high))
                case _:
                    # Newest: walk back far enough to fill the result budget,
                    # rather than sitting at the end waiting for new traffic.
                    per_partition = max(1, request.max_results // max(1, len(wanted)))
                    start = max(low, high - per_partition * 4)
            assignments.append(TopicPartition(request.topic, partition, start))

        return assignments

    def _scan_blocking(
        self,
        request: ScanRequest,
        masker: Masker,
        message_filter: MessageFilter | None,
        should_stop: Callable[[], bool],
    ) -> ScanResult:
        started = time.monotonic()
        consumer = self._build_consumer()
        messages: list[ScannedMessage] = []
        scanned = 0
        stop_reason = StopReason.COMPLETED
        partitions: list[int] = []
        finished: set[int] = set()

        try:
            assignments = self._assign(consumer, request)
            partitions = sorted(tp.partition for tp in assignments)
            consumer.assign(assignments)

            while True:
                if should_stop():
                    stop_reason = StopReason.CANCELLED
                    break
                if len(messages) >= request.max_results:
                    stop_reason = StopReason.MAX_RESULTS
                    break
                if scanned >= request.max_scanned:
                    stop_reason = StopReason.SCANNED_BUDGET
                    break
                if time.monotonic() - started >= request.max_seconds:
                    stop_reason = StopReason.TIME_BUDGET
                    break
                if len(finished) >= len(assignments):
                    stop_reason = StopReason.COMPLETED
                    break

                record = consumer.poll(0.5)
                if record is None:
                    continue

                error = record.error()
                if error is not None:
                    # End of partition is a normal terminating condition here,
                    # not a failure.
                    if error.code() == -191:  # _PARTITION_EOF
                        eof_partition = record.partition()
                        if eof_partition is not None:
                            finished.add(eof_partition)
                        continue
                    raise translate_kafka_error(Exception(error))

                record_partition = record.partition()
                record_offset = record.offset()
                if record_partition is None or record_offset is None:
                    continue

                scanned += 1
                key = decode_payload(record.key())
                value = decode_payload(record.value())
                timestamp_type, timestamp = record.timestamp()

                message = ScannedMessage(
                    topic=record.topic() or request.topic,
                    partition=record_partition,
                    offset=record_offset,
                    timestamp=timestamp if timestamp > 0 else None,
                    timestamp_type={0: "not_available", 1: "create_time", 2: "log_append_time"}.get(
                        timestamp_type
                    ),
                    key=key,
                    value=value,
                    headers=_headers_to_dict(record.headers()),
                )

                if message_filter is not None and not message_filter.matches(
                    _record_for_filter(message)
                ):
                    continue

                # Mask only what is actually returned, so filtering still sees
                # true values while the browser never receives them.
                if masker.enabled:
                    masked_value = masker.mask(message.value.value, topic=message.topic)
                    masked_key = masker.mask(message.key.value, topic=message.topic)
                    message.value.value = masked_value.value
                    message.key.value = masked_key.value
                    message.masked = masked_value.applied or masked_key.applied

                messages.append(message)

        except KafkaGateError:
            raise
        except Exception as exc:
            raise translate_kafka_error(exc) from exc
        finally:
            # Always close: an abandoned consumer holds a broker connection.
            with contextlib.suppress(Exception):
                consumer.close()

        return ScanResult(
            messages=messages,
            scanned=scanned,
            elapsed_seconds=round(time.monotonic() - started, 3),
            stop_reason=stop_reason,
            partitions_scanned=partitions,
        )

    async def scan(
        self,
        request: ScanRequest,
        *,
        masker: Masker,
        cancel_event: asyncio.Event | None = None,
    ) -> ScanResult:
        message_filter = (
            MessageFilter.compile(request.filter_expression) if request.filter_expression else None
        )
        loop = asyncio.get_running_loop()

        def should_stop() -> bool:
            return cancel_event.is_set() if cancel_event else False

        return await loop.run_in_executor(
            self._executor,
            lambda: self._scan_blocking(request, masker, message_filter, should_stop),
        )


def format_counts(messages: list[ScannedMessage]) -> dict[str, int]:
    """Tally payload formats, so the UI can explain a screen full of hex."""
    counts: dict[str, int] = {}
    for message in messages:
        key = str(message.value.format or PayloadFormat.NULL)
        counts[key] = counts.get(key, 0) + 1
    return counts
