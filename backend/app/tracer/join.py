"""Topic-to-topic latency tracing.

Pick two topics, a join key expressed as a JMESPath expression on each side,
and a timestamp source. The tracer scans both, matches records by key, and
reports the distribution of the time between them.

Deliberate constraints, because this is the most expensive thing the console
can do:

* It runs only while a user asks for it. Nothing traces in the background.
* Both scans are bounded by the same budgets as a message search.
* The key cache is bounded, and unmatched records are counted rather than
  retained, so memory cannot grow with the topic.
* The result is labelled an estimate. Records that never matched are reported,
  so a low sample count is visible rather than silently flattering.
"""

from __future__ import annotations

from enum import StrEnum

import jmespath
from jmespath.exceptions import JMESPathError
from pydantic import BaseModel, Field

from app.search.scan import ScannedMessage


class TimestampSource(StrEnum):
    KAFKA = "kafka"
    """The broker record timestamp."""

    FIELD = "field"
    """A field inside the payload, parsed as epoch milliseconds."""


class TraceRequest(BaseModel):
    source_topic: str
    target_topic: str
    source_key: str = Field(description="JMESPath producing the join key on the source side.")
    target_key: str = Field(description="JMESPath producing the join key on the target side.")
    timestamp_source: TimestampSource = TimestampSource.KAFKA
    source_timestamp_field: str | None = None
    target_timestamp_field: str | None = None
    window_minutes: int = Field(default=60, ge=1, le=1440)
    max_messages: int = Field(default=5_000, ge=1, le=50_000)
    max_seconds: float = Field(default=30.0, gt=0, le=120.0)


class LatencyBucket(BaseModel):
    label: str
    count: int


class TraceResult(BaseModel):
    source_topic: str
    target_topic: str
    matched: int
    source_scanned: int
    target_scanned: int
    unmatched_target: int
    """Target records whose key was not seen on the source side."""

    p50_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    min_ms: float | None = None
    max_ms: float | None = None
    mean_ms: float | None = None
    buckets: list[LatencyBucket] = Field(default_factory=list)
    negative_count: int = 0
    """Pairs where the target predates the source; usually a clock or key problem."""

    note: str = (
        "An estimate. Records are matched by key within the scanned window, so "
        "pairs outside that window are not counted."
    )


# Bounded so a trace cannot grow with the topic.
MAX_KEY_CACHE = 200_000


class _Extractor:
    """Compiles a JMESPath expression once and applies it per message."""

    __slots__ = ("_compiled", "expression")

    def __init__(self, expression: str) -> None:
        self.expression = expression
        self._compiled = jmespath.compile(expression)

    def key_of(self, message: ScannedMessage) -> str | None:
        record = {
            "key": message.key.value,
            "value": message.value.value,
            "headers": message.headers,
            "topic": message.topic,
            "partition": message.partition,
            "offset": message.offset,
            "timestamp": message.timestamp,
        }
        try:
            value = self._compiled.search(record)
        except (JMESPathError, Exception):
            return None
        if value is None:
            return None
        return str(value)


def _timestamp_of(
    message: ScannedMessage, source: TimestampSource, field_expression: str | None
) -> float | None:
    if source is TimestampSource.KAFKA:
        return float(message.timestamp) if message.timestamp is not None else None

    if not field_expression:
        return None
    try:
        raw = jmespath.compile(field_expression).search(
            {"value": message.value.value, "key": message.key.value, "headers": message.headers}
        )
    except (JMESPathError, Exception):
        return None

    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        # Accept epoch millis as a string, or an ISO timestamp.
        try:
            return float(raw)
        except ValueError:
            from datetime import datetime

            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000
            except ValueError:
                return None
    return None


def _percentile(ordered: list[float], fraction: float) -> float:
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def correlate(
    request: TraceRequest,
    source_messages: list[ScannedMessage],
    target_messages: list[ScannedMessage],
    *,
    source_scanned: int,
    target_scanned: int,
) -> TraceResult:
    """Match target records back to source records and summarise the deltas."""
    result = TraceResult(
        source_topic=request.source_topic,
        target_topic=request.target_topic,
        matched=0,
        source_scanned=source_scanned,
        target_scanned=target_scanned,
        unmatched_target=0,
    )

    try:
        source_extractor = _Extractor(request.source_key)
        target_extractor = _Extractor(request.target_key)
    except JMESPathError:
        return result

    # Earliest occurrence per key: a repeated key means the first source record
    # is the one the target most plausibly derives from.
    earliest: dict[str, float] = {}
    for message in source_messages:
        key = source_extractor.key_of(message)
        if key is None or len(earliest) >= MAX_KEY_CACHE:
            continue
        stamp = _timestamp_of(message, request.timestamp_source, request.source_timestamp_field)
        if stamp is None:
            continue
        if key not in earliest or stamp < earliest[key]:
            earliest[key] = stamp

    deltas: list[float] = []
    for message in target_messages:
        key = target_extractor.key_of(message)
        if key is None or key not in earliest:
            result.unmatched_target += 1
            continue
        stamp = _timestamp_of(message, request.timestamp_source, request.target_timestamp_field)
        if stamp is None:
            result.unmatched_target += 1
            continue
        delta = stamp - earliest[key]
        if delta < 0:
            result.negative_count += 1
            continue
        deltas.append(delta)

    result.matched = len(deltas)
    if not deltas:
        return result

    ordered = sorted(deltas)
    result.min_ms = round(ordered[0], 2)
    result.max_ms = round(ordered[-1], 2)
    result.mean_ms = round(sum(ordered) / len(ordered), 2)
    result.p50_ms = round(_percentile(ordered, 0.50), 2)
    result.p95_ms = round(_percentile(ordered, 0.95), 2)
    result.p99_ms = round(_percentile(ordered, 0.99), 2)

    # Log-ish buckets, because latency distributions are long-tailed and a
    # linear histogram would put everything in the first bar.
    edges = [10, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000, 30_000, 60_000]
    counts = [0] * (len(edges) + 1)
    for delta in ordered:
        placed = False
        for index, edge in enumerate(edges):
            if delta < edge:
                counts[index] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1

    labels = [f"<{edge}ms" for edge in edges] + [f">{edges[-1]}ms"]
    result.buckets = [
        LatencyBucket(label=label, count=count)
        for label, count in zip(labels, counts, strict=True)
        if count > 0
    ]
    return result
