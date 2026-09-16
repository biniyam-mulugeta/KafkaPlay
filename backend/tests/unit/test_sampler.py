"""Lag history, velocity, ETA, throughput and the heatmap.

These are pure arithmetic over stored offsets, so they run with no broker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from app.sampler.series import (
    LagTrend,
    heatmap,
    lag_history,
    topic_throughput,
)
from app.store.models import OffsetSample, TopicOffsetSample
from app.store.session import create_db_engine, init_db


@pytest.fixture
def engine(tmp_path) -> Engine:  # type: ignore[no-untyped-def]
    instance = create_db_engine(f"sqlite:///{tmp_path / 'metrics.db'}")
    init_db(instance)
    return instance


def seed_lag(
    engine: Engine,
    lags: list[int],
    *,
    committed: list[int] | None = None,
    high: list[int] | None = None,
    interval_seconds: int = 30,
    group_id: str = "g",
    topic: str = "t",
) -> None:
    """Write a lag series ending now, spaced by interval_seconds."""
    now = datetime.now(UTC)
    with Session(engine) as session:
        for index, lag in enumerate(lags):
            at = now - timedelta(seconds=interval_seconds * (len(lags) - 1 - index))
            session.add(
                OffsetSample(
                    at=at,
                    cluster="c",
                    group_id=group_id,
                    topic=topic,
                    partition=0,
                    committed_offset=committed[index] if committed else None,
                    high_watermark=high[index] if high else None,
                    lag=lag,
                )
            )
        session.commit()


class TestLagTrend:
    def test_falling_behind(self, engine: Engine) -> None:
        seed_lag(engine, [100, 400, 700, 1000, 1300])
        result = lag_history(engine, cluster="c", group_id="g")
        assert result.trend is LagTrend.FALLING_BEHIND
        assert result.lag_velocity is not None and result.lag_velocity > 0
        # Not catching up, so there is no honest ETA to give.
        assert result.eta_seconds is None

    def test_catching_up_with_eta(self, engine: Engine) -> None:
        # Falling by 300 every 30s = -10/s. 100 remaining => ~10s.
        seed_lag(engine, [1300, 1000, 700, 400, 100])
        result = lag_history(engine, cluster="c", group_id="g")
        assert result.trend is LagTrend.CATCHING_UP
        assert result.lag_velocity is not None and result.lag_velocity < 0
        assert result.eta_seconds is not None
        assert 5 < result.eta_seconds < 20

    def test_stable(self, engine: Engine) -> None:
        seed_lag(engine, [500, 501, 499, 500, 500])
        result = lag_history(engine, cluster="c", group_id="g")
        assert result.trend is LagTrend.STABLE

    def test_caught_up_has_zero_eta(self, engine: Engine) -> None:
        seed_lag(engine, [400, 300, 200, 100, 0])
        result = lag_history(engine, cluster="c", group_id="g")
        assert result.current_lag == 0
        assert result.eta_seconds == 0.0

    def test_single_sample_has_no_trend(self, engine: Engine) -> None:
        seed_lag(engine, [100])
        result = lag_history(engine, cluster="c", group_id="g")
        assert result.trend is LagTrend.UNKNOWN
        assert result.lag_velocity is None

    def test_no_samples_returns_empty(self, engine: Engine) -> None:
        result = lag_history(engine, cluster="c", group_id="nobody")
        assert result.lag == []
        assert result.current_lag is None
        assert result.trend is LagTrend.UNKNOWN

    def test_trend_is_robust_to_one_noisy_reading(self, engine: Engine) -> None:
        # A least-squares slope should not flip on a single spike.
        seed_lag(engine, [1000, 800, 5000, 400, 200])
        result = lag_history(engine, cluster="c", group_id="g")
        assert result.trend is LagTrend.CATCHING_UP


class TestRates:
    def test_consume_and_produce_rates(self, engine: Engine) -> None:
        # Committed advances 300 per 30s = 10/s; the log advances 600 = 20/s.
        seed_lag(
            engine,
            [0, 300, 600, 900],
            committed=[0, 300, 600, 900],
            high=[0, 600, 1200, 1800],
        )
        result = lag_history(engine, cluster="c", group_id="g")
        consume = [p.value for p in result.consume_rate if p.value is not None]
        produce = [p.value for p in result.produce_rate if p.value is not None]
        assert consume and all(abs(v - 10.0) < 0.5 for v in consume)
        assert produce and all(abs(v - 20.0) < 0.5 for v in produce)

    def test_counter_reset_is_unknown_not_negative(self, engine: Engine) -> None:
        # Retention or a topic recreate makes the offset go backwards; a
        # negative "rate" would be nonsense.
        seed_lag(engine, [0, 0, 0], committed=[1000, 2000, 5], high=[1000, 2000, 5])
        result = lag_history(engine, cluster="c", group_id="g")
        values = [p.value for p in result.consume_rate]
        assert any(value is None for value in values)
        assert all(value is None or value >= 0 for value in values)


class TestWindowing:
    def test_old_samples_are_excluded(self, engine: Engine) -> None:
        now = datetime.now(UTC)
        with Session(engine) as session:
            session.add(
                OffsetSample(
                    at=now - timedelta(hours=5),
                    cluster="c",
                    group_id="g",
                    topic="t",
                    partition=0,
                    lag=9999,
                )
            )
            session.add(
                OffsetSample(at=now, cluster="c", group_id="g", topic="t", partition=0, lag=10)
            )
            session.commit()

        result = lag_history(engine, cluster="c", group_id="g", window_minutes=60)
        assert result.sampled_points == 1
        assert result.current_lag == 10

    def test_filtering_by_topic(self, engine: Engine) -> None:
        seed_lag(engine, [10, 20], topic="a")
        seed_lag(engine, [500, 600], topic="b")
        result = lag_history(engine, cluster="c", group_id="g", topic="b")
        assert result.current_lag == 600

    def test_lag_is_summed_across_partitions(self, engine: Engine) -> None:
        now = datetime.now(UTC)
        with Session(engine) as session:
            for partition in range(3):
                session.add(
                    OffsetSample(
                        at=now,
                        cluster="c",
                        group_id="g",
                        topic="t",
                        partition=partition,
                        lag=100,
                    )
                )
            session.commit()
        result = lag_history(engine, cluster="c", group_id="g")
        assert result.current_lag == 300

    def test_other_clusters_are_not_mixed_in(self, engine: Engine) -> None:
        now = datetime.now(UTC)
        with Session(engine) as session:
            session.add(
                OffsetSample(at=now, cluster="other", group_id="g", topic="t", partition=0, lag=999)
            )
            session.commit()
        assert lag_history(engine, cluster="c", group_id="g").current_lag is None


def seed_topic(engine: Engine, highs: list[int], *, topic: str = "t", partitions: int = 1) -> None:
    now = datetime.now(UTC)
    with Session(engine) as session:
        for index, high in enumerate(highs):
            at = now - timedelta(seconds=30 * (len(highs) - 1 - index))
            for partition in range(partitions):
                session.add(
                    TopicOffsetSample(
                        at=at,
                        cluster="c",
                        topic=topic,
                        partition=partition,
                        low_watermark=0,
                        high_watermark=high,
                    )
                )
        session.commit()


class TestThroughput:
    def test_rate_is_computed(self, engine: Engine) -> None:
        seed_topic(engine, [0, 300, 600, 900])  # 300 per 30s = 10/s
        result = topic_throughput(engine, cluster="c", topic="t")
        assert result.points
        assert result.average is not None and abs(result.average - 10.0) < 0.5
        assert result.peak is not None

    def test_no_data(self, engine: Engine) -> None:
        result = topic_throughput(engine, cluster="c", topic="missing")
        assert result.points == []
        assert result.average is None


class TestHeatmap:
    def test_throughput_heatmap_has_a_cell_per_partition(self, engine: Engine) -> None:
        seed_topic(engine, [0, 300, 600], topic="orders", partitions=3)
        result = heatmap(engine, cluster="c", metric="throughput")
        assert result.metric == "throughput"
        assert result.topics == ["orders"]
        assert len(result.cells) == 3
        assert result.max_value > 0

    def test_lag_heatmap_uses_the_latest_value(self, engine: Engine) -> None:
        seed_lag(engine, [100, 50], topic="orders")
        result = heatmap(engine, cluster="c", metric="lag")
        assert result.metric == "lag"
        assert result.cells
        assert result.cells[0].value == 50.0

    def test_empty_heatmap(self, engine: Engine) -> None:
        result = heatmap(engine, cluster="c")
        assert result.cells == []
        assert result.max_value == 0.0
