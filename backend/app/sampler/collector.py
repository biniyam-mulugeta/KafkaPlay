"""The built-in offset sampler.

This is the piece that lets lag history, lag velocity, time-to-catch-up,
throughput and the partition heatmap work against *any* broker, with no
Prometheus and no JMX. Managed clusters rarely expose JMX, which is exactly
where those charts are needed most.

Load discipline:

* One pass per interval per cluster, batched: list groups, read their
  committed offsets, read watermarks. No shadow consumers.
* Above a partition-count threshold the interval stretches automatically, so
  pointing this at a very large cluster does not become the load problem the
  design exists to avoid.
* It stores offsets only. Numbers, never message content.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, delete
from sqlmodel import Session, col, select

from app.clusters.registry import ClusterRegistry
from app.kafka.errors import KafkaGateError
from app.kafka.gates import GateRegistry
from app.logging import get_logger
from app.store.models import OffsetSample, TopicOffsetSample, utcnow

log = get_logger(__name__)


class OffsetSampler:
    def __init__(
        self,
        engine: Engine,
        gates: GateRegistry,
        clusters: ClusterRegistry,
        *,
        interval_seconds: int = 30,
        retention_days: int = 7,
        max_partitions: int = 2000,
    ) -> None:
        self._engine = engine
        self._gates = gates
        self._clusters = clusters
        self._interval = interval_seconds
        self._retention = retention_days
        self._max_partitions = max_partitions
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_run_at: datetime | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="offset-sampler")
            log.info("sampler_started", interval_seconds=self._interval)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            delay = self._interval
            try:
                sampled_partitions = await self.sample_once()
                # Back off proportionally on large clusters rather than
                # hammering them every interval.
                if sampled_partitions > self._max_partitions:
                    factor = sampled_partitions / self._max_partitions
                    delay = int(self._interval * min(factor, 10))
                    log.info(
                        "sampler_backing_off",
                        partitions=sampled_partitions,
                        interval_seconds=delay,
                    )
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                log.warning("sampler_pass_failed", error=str(exc))

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                continue

    async def sample_once(self) -> int:
        """One sampling pass over every configured cluster."""
        total_partitions = 0
        rows: list[OffsetSample] = []
        topic_rows: list[TopicOffsetSample] = []
        now = utcnow()

        for cluster in self._clusters.list():
            try:
                gate = await self._gates.get(cluster.name)
            except Exception:
                continue

            # Topic watermarks: needed for throughput and the heatmap, and for
            # topics that no group consumes.
            try:
                topics = await gate.list_topics(include_internal=False)
                pairs: list[tuple[str, int]] = []
                for topic in topics:
                    detail = await gate.describe_topic(topic.name, with_watermarks=False)
                    pairs.extend((topic.name, p.partition) for p in detail.partitions)

                total_partitions += len(pairs)
                if pairs:
                    marks = await gate.watermarks(pairs)
                    for (topic_name, partition), (low, high) in marks.items():
                        topic_rows.append(
                            TopicOffsetSample(
                                at=now,
                                cluster=cluster.name,
                                topic=topic_name,
                                partition=partition,
                                low_watermark=low,
                                high_watermark=high,
                            )
                        )
            except KafkaGateError as exc:
                log.debug("sampler_topics_unavailable", cluster=cluster.name, error=exc.message)

            # Consumer group lag.
            try:
                groups = await gate.list_groups()
            except KafkaGateError:
                continue

            for group in groups:
                try:
                    lags = await gate.group_lag(group.group_id)
                except KafkaGateError:
                    continue
                for lag in lags:
                    rows.append(
                        OffsetSample(
                            at=now,
                            cluster=cluster.name,
                            group_id=group.group_id,
                            topic=lag.topic,
                            partition=lag.partition,
                            committed_offset=lag.current_offset,
                            high_watermark=lag.high_watermark,
                            lag=lag.lag,
                        )
                    )

        if rows or topic_rows:
            with Session(self._engine) as session:
                session.add_all(rows)
                session.add_all(topic_rows)
                session.commit()

        self.last_run_at = now
        self._apply_retention()
        return total_partitions

    def _apply_retention(self) -> None:
        """Drop samples older than the retention window."""
        cutoff = datetime.now(UTC) - timedelta(days=self._retention)
        with Session(self._engine) as session:
            session.exec(delete(OffsetSample).where(col(OffsetSample.at) < cutoff))
            session.exec(delete(TopicOffsetSample).where(col(TopicOffsetSample.at) < cutoff))
            session.commit()

    def sample_count(self) -> int:
        with Session(self._engine) as session:
            return len(session.exec(select(OffsetSample.id)).all())
