"""Turning sampled offsets into the series the UI draws.

Everything here is arithmetic over stored offsets -- no broker calls -- so
these endpoints are cheap and safe to poll.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from itertools import pairwise

from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.store.models import OffsetSample, TopicOffsetSample


class LagTrend(StrEnum):
    CATCHING_UP = "catching_up"
    STABLE = "stable"
    FALLING_BEHIND = "falling_behind"
    UNKNOWN = "unknown"


class SeriesPoint(BaseModel):
    at: datetime
    value: float | None = None


class LagHistory(BaseModel):
    group_id: str
    topic: str | None = None
    partition: int | None = None
    lag: list[SeriesPoint] = Field(default_factory=list)
    consume_rate: list[SeriesPoint] = Field(
        default_factory=list, description="Messages/second committed by the group."
    )
    produce_rate: list[SeriesPoint] = Field(
        default_factory=list, description="Messages/second appended to the log."
    )
    trend: LagTrend = LagTrend.UNKNOWN
    lag_velocity: float | None = Field(
        default=None, description="Change in lag per second. Negative means catching up."
    )
    eta_seconds: float | None = Field(
        default=None, description="Estimated time to clear the lag, when catching up."
    )
    current_lag: int | None = None
    sampled_points: int = 0


class ThroughputPoint(BaseModel):
    at: datetime
    messages_per_second: float


class TopicThroughput(BaseModel):
    topic: str
    points: list[ThroughputPoint] = Field(default_factory=list)
    average: float | None = None
    peak: float | None = None


class HeatmapCell(BaseModel):
    topic: str
    partition: int
    value: float
    """Messages/second, or lag, depending on the requested metric."""


class Heatmap(BaseModel):
    metric: str
    topics: list[str] = Field(default_factory=list)
    max_partition: int = 0
    cells: list[HeatmapCell] = Field(default_factory=list)
    max_value: float = 0.0


# Below this many seconds between samples, rate arithmetic is too noisy to be
# meaningful; below this much movement, treat lag as stable.
_MIN_INTERVAL_SECONDS = 1.0
_STABLE_BAND = 0.5


def _rate(
    points: list[tuple[datetime, int | None]],
) -> list[SeriesPoint]:
    """First difference of a monotonically increasing counter, per second.

    Offsets only go up, so a decrease means the topic was recreated or
    retention removed records; those intervals are reported as unknown rather
    than as a negative rate.
    """
    series: list[SeriesPoint] = []
    for (prev_at, prev_value), (at, value) in pairwise(points):
        if prev_value is None or value is None:
            series.append(SeriesPoint(at=at, value=None))
            continue
        seconds = (at - prev_at).total_seconds()
        if seconds < _MIN_INTERVAL_SECONDS:
            continue
        delta = value - prev_value
        series.append(SeriesPoint(at=at, value=None if delta < 0 else delta / seconds))
    return series


def _linear_slope(points: list[tuple[datetime, float]]) -> float | None:
    """Least-squares slope, used for lag velocity.

    A slope is far steadier than comparing the first and last sample, which
    would make the trend flip on a single noisy reading.
    """
    if len(points) < 2:
        return None
    base = points[0][0]
    xs = [(at - base).total_seconds() for at, _ in points]
    ys = [value for _, value in points]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator


def lag_history(
    engine: Engine,
    *,
    cluster: str,
    group_id: str,
    topic: str | None = None,
    partition: int | None = None,
    window_minutes: int = 60,
) -> LagHistory:
    since = datetime.now(UTC) - timedelta(minutes=window_minutes)

    with Session(engine) as session:
        statement = (
            select(OffsetSample)
            .where(OffsetSample.cluster == cluster)
            .where(OffsetSample.group_id == group_id)
            .where(OffsetSample.at >= since)
            .order_by(OffsetSample.at)  # type: ignore[arg-type]
        )
        if topic is not None:
            statement = statement.where(OffsetSample.topic == topic)
        if partition is not None:
            statement = statement.where(OffsetSample.partition == partition)
        rows = list(session.exec(statement).all())

    result = LagHistory(group_id=group_id, topic=topic, partition=partition)
    if not rows:
        return result

    # Sum across partitions at each timestamp, so a group's total lag is one
    # line rather than one per partition.
    lag_by_time: dict[datetime, int] = defaultdict(int)
    committed_by_time: dict[datetime, int] = defaultdict(int)
    high_by_time: dict[datetime, int] = defaultdict(int)
    known_lag: set[datetime] = set()

    for row in rows:
        if row.lag is not None:
            lag_by_time[row.at] += row.lag
            known_lag.add(row.at)
        if row.committed_offset is not None:
            committed_by_time[row.at] += row.committed_offset
        if row.high_watermark is not None:
            high_by_time[row.at] += row.high_watermark

    stamps = sorted(known_lag)
    result.lag = [SeriesPoint(at=at, value=float(lag_by_time[at])) for at in stamps]
    result.sampled_points = len(stamps)
    result.current_lag = int(lag_by_time[stamps[-1]]) if stamps else None

    committed_stamps = sorted(committed_by_time)
    committed_series: list[tuple[datetime, int | None]] = [
        (at, committed_by_time[at]) for at in committed_stamps
    ]
    result.consume_rate = _rate(committed_series)
    high_stamps = sorted(high_by_time)
    high_series: list[tuple[datetime, int | None]] = [(at, high_by_time[at]) for at in high_stamps]
    result.produce_rate = _rate(high_series)

    slope = _linear_slope([(at, float(lag_by_time[at])) for at in stamps])
    if slope is not None:
        result.lag_velocity = slope
        if slope < -_STABLE_BAND:
            result.trend = LagTrend.CATCHING_UP
            current = result.current_lag or 0
            # Only meaningful while the group is actually gaining ground.
            result.eta_seconds = round(current / abs(slope), 1) if current > 0 else 0.0
        elif slope > _STABLE_BAND:
            result.trend = LagTrend.FALLING_BEHIND
        else:
            result.trend = LagTrend.STABLE

    return result


def topic_throughput(
    engine: Engine,
    *,
    cluster: str,
    topic: str,
    window_minutes: int = 60,
) -> TopicThroughput:
    since = datetime.now(UTC) - timedelta(minutes=window_minutes)

    with Session(engine) as session:
        rows = list(
            session.exec(
                select(TopicOffsetSample)
                .where(TopicOffsetSample.cluster == cluster)
                .where(TopicOffsetSample.topic == topic)
                .where(TopicOffsetSample.at >= since)
                .order_by(TopicOffsetSample.at)  # type: ignore[arg-type]
            ).all()
        )

    totals: dict[datetime, int] = defaultdict(int)
    for row in rows:
        if row.high_watermark is not None:
            totals[row.at] += row.high_watermark

    stamps = sorted(totals)
    series: list[tuple[datetime, int | None]] = [(at, totals[at]) for at in stamps]
    rates = _rate(series)
    points = [
        ThroughputPoint(at=point.at, messages_per_second=point.value)
        for point in rates
        if point.value is not None
    ]

    values = [point.messages_per_second for point in points]
    return TopicThroughput(
        topic=topic,
        points=points,
        average=round(sum(values) / len(values), 3) if values else None,
        peak=round(max(values), 3) if values else None,
    )


def heatmap(
    engine: Engine,
    *,
    cluster: str,
    metric: str = "throughput",
    window_minutes: int = 30,
) -> Heatmap:
    """Topics x partitions, coloured by throughput or lag.

    Skew and hot partitions are obvious here in a way they never are in a
    table of numbers.
    """
    since = datetime.now(UTC) - timedelta(minutes=window_minutes)
    result = Heatmap(metric=metric)

    with Session(engine) as session:
        if metric == "lag":
            rows = list(
                session.exec(
                    select(OffsetSample)
                    .where(OffsetSample.cluster == cluster)
                    .where(OffsetSample.at >= since)
                    .order_by(OffsetSample.at)  # type: ignore[arg-type]
                ).all()
            )
            latest: dict[tuple[str, int], float] = {}
            for row in rows:
                if row.lag is not None:
                    latest[(row.topic, row.partition)] = float(row.lag)
            cells = [
                HeatmapCell(topic=topic, partition=partition, value=value)
                for (topic, partition), value in latest.items()
            ]
        else:
            topic_rows = list(
                session.exec(
                    select(TopicOffsetSample)
                    .where(TopicOffsetSample.cluster == cluster)
                    .where(TopicOffsetSample.at >= since)
                    .order_by(TopicOffsetSample.at)  # type: ignore[arg-type]
                ).all()
            )
            per_partition: dict[tuple[str, int], list[tuple[datetime, int | None]]] = defaultdict(
                list
            )
            for topic_row in topic_rows:
                if topic_row.high_watermark is not None:
                    per_partition[(topic_row.topic, topic_row.partition)].append(
                        (topic_row.at, topic_row.high_watermark)
                    )

            cells = []
            for (topic, partition), series in per_partition.items():
                rates = _rate(series)
                values = [point.value for point in rates if point.value is not None]
                if values:
                    cells.append(
                        HeatmapCell(
                            topic=topic,
                            partition=partition,
                            value=round(sum(values) / len(values), 3),
                        )
                    )

    cells.sort(key=lambda cell: (cell.topic, cell.partition))
    result.cells = cells
    result.topics = sorted({cell.topic for cell in cells})
    result.max_partition = max((cell.partition for cell in cells), default=0)
    result.max_value = max((cell.value for cell in cells), default=0.0)
    return result
