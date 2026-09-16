"""Custom dashboard panels.

A panel is a small, declarative query:

    source   -- a topic, optionally restricted to some partitions
    extract  -- a JMESPath expression over the decoded record
    visualise-- throughput, split-by, histogram, top-N, or a single stat
    window   -- last N minutes or last N messages, sampled

This is what replaces a hard-coded pipeline page: anything specific to one
deployment is expressed as a dashboard the operator builds and exports, not as
product code.

Scan cost is bounded exactly like the message browser, because a panel is a
scan. Panels on the same dashboard that read the same topic share one scan.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import jmespath
from jmespath.exceptions import JMESPathError
from pydantic import BaseModel, Field

from app.search.scan import ScannedMessage


class PanelType(StrEnum):
    THROUGHPUT = "throughput"
    SPLIT_BY = "split_by"
    HISTOGRAM = "histogram"
    TOP_N = "top_n"
    STAT = "stat"


class StatOp(StrEnum):
    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    P95 = "p95"


class PanelSpec(BaseModel):
    """The saved definition of one panel."""

    id: str
    title: str
    type: PanelType
    topic: str
    partitions: list[int] | None = None
    # JMESPath over {key, value, headers, topic, partition, offset, timestamp}
    extract: str | None = None
    filter: str | None = None

    window_minutes: int = Field(default=60, ge=1, le=10_080)
    max_messages: int = Field(default=5_000, ge=1, le=50_000)

    # split_by / top_n
    top_n: int = Field(default=10, ge=1, le=100)
    # histogram
    buckets: int = Field(default=20, ge=2, le=100)
    thresholds: list[float] = Field(
        default_factory=list,
        description="Vertical marker lines, e.g. an alerting threshold.",
    )
    # stat
    stat_op: StatOp = StatOp.COUNT
    unit: str | None = None

    # Persisting results is opt-in, and stores masked aggregates only.
    persist: bool = False
    retention_days: int = Field(default=7, ge=1, le=365)


class Bucket(BaseModel):
    label: str
    value: float


class PanelResult(BaseModel):
    id: str
    title: str
    type: PanelType
    topic: str
    sampled: int
    matched: int
    elapsed_seconds: float
    stop_reason: str
    # One of these is populated depending on the panel type.
    buckets: list[Bucket] = Field(default_factory=list)
    series: list[dict[str, Any]] = Field(default_factory=list)
    stat: float | None = None
    unit: str | None = None
    thresholds: list[float] = Field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class ExtractedValues:
    numbers: list[float] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    timestamps: list[int] = field(default_factory=list)


def _record(message: ScannedMessage) -> dict[str, Any]:
    return {
        "key": message.key.value,
        "value": message.value.value,
        "headers": message.headers,
        "topic": message.topic,
        "partition": message.partition,
        "offset": message.offset,
        "timestamp": message.timestamp,
    }


def extract(messages: list[ScannedMessage], expression: str | None) -> ExtractedValues:
    """Pull one value per message, keeping numbers and labels apart."""
    result = ExtractedValues()
    compiled = None
    if expression:
        try:
            compiled = jmespath.compile(expression)
        except JMESPathError:
            return result

    for message in messages:
        if message.timestamp is not None:
            result.timestamps.append(message.timestamp)

        if compiled is None:
            continue
        try:
            value = compiled.search(_record(message))
        except (JMESPathError, Exception):
            continue

        if isinstance(value, bool):
            # bool is an int subclass; treat it as a label, which is what an
            # operator means by splitting on a boolean field.
            result.labels.append(str(value).lower())
        elif isinstance(value, (int, float)):
            result.numbers.append(float(value))
        elif isinstance(value, str):
            result.labels.append(value)
        elif value is not None:
            result.labels.append(str(value))

    return result


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def build_throughput(messages: list[ScannedMessage], spec: PanelSpec) -> list[dict[str, Any]]:
    """Messages per second, bucketed over the scanned window."""
    stamps = sorted(m.timestamp for m in messages if m.timestamp is not None)
    if len(stamps) < 2:
        return []

    span_ms = stamps[-1] - stamps[0]
    if span_ms <= 0:
        return []

    bucket_count = min(spec.buckets, max(2, len(stamps) // 5 or 2))
    width = max(1, span_ms // bucket_count)

    counts: dict[int, int] = defaultdict(int)
    for stamp in stamps:
        counts[(stamp - stamps[0]) // width] += 1

    return [
        {
            "at": stamps[0] + index * width,
            "messages_per_second": round(count / (width / 1000), 3),
        }
        for index, count in sorted(counts.items())
    ]


def build_panel(
    spec: PanelSpec,
    messages: list[ScannedMessage],
    *,
    sampled: int,
    elapsed_seconds: float,
    stop_reason: str,
) -> PanelResult:
    result = PanelResult(
        id=spec.id,
        title=spec.title,
        type=spec.type,
        topic=spec.topic,
        sampled=sampled,
        matched=len(messages),
        elapsed_seconds=elapsed_seconds,
        stop_reason=stop_reason,
        unit=spec.unit,
        thresholds=spec.thresholds,
    )

    values = extract(messages, spec.extract)

    match spec.type:
        case PanelType.THROUGHPUT:
            result.series = build_throughput(messages, spec)

        case PanelType.SPLIT_BY:
            if not spec.extract:
                result.error = "this panel needs an extract expression"
                return result
            counts = Counter(values.labels)
            result.buckets = [
                Bucket(label=label, value=float(count))
                for label, count in counts.most_common(spec.top_n)
            ]

        case PanelType.TOP_N:
            if not spec.extract:
                result.error = "this panel needs an extract expression"
                return result
            counts = Counter(values.labels)
            result.buckets = [
                Bucket(label=label, value=float(count))
                for label, count in counts.most_common(spec.top_n)
            ]

        case PanelType.HISTOGRAM:
            if not values.numbers:
                result.error = "no numeric values matched the extract expression"
                return result
            low = min(values.numbers)
            high = max(values.numbers)
            if high == low:
                result.buckets = [Bucket(label=f"{low:g}", value=float(len(values.numbers)))]
                return result
            width = (high - low) / spec.buckets
            counts_by_bucket: dict[int, int] = defaultdict(int)
            for number in values.numbers:
                index = min(spec.buckets - 1, int((number - low) / width))
                counts_by_bucket[index] += 1
            result.buckets = [
                Bucket(
                    label=f"{low + index * width:.4g}",
                    value=float(counts_by_bucket.get(index, 0)),
                )
                for index in range(spec.buckets)
            ]

        case PanelType.STAT:
            numbers = values.numbers
            match spec.stat_op:
                case StatOp.COUNT:
                    result.stat = float(len(messages))
                case StatOp.SUM:
                    result.stat = sum(numbers) if numbers else 0.0
                case StatOp.AVG:
                    result.stat = sum(numbers) / len(numbers) if numbers else None
                case StatOp.MIN:
                    result.stat = min(numbers) if numbers else None
                case StatOp.MAX:
                    result.stat = max(numbers) if numbers else None
                case StatOp.P95:
                    result.stat = _percentile(numbers, 0.95) if numbers else None
            if result.stat is not None:
                result.stat = round(result.stat, 4)

    return result
