"""Alert evaluation, debounce, cooldown and notification signing."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.alerts.evaluator import AlertEvaluator, evaluate_rule
from app.alerts.notify import SIGNATURE_HEADER, Notifier, sign
from app.config import Settings
from app.store.models import (
    AlertFiring,
    AlertKind,
    AlertRule,
    AlertSeverity,
    AlertState,
    OffsetSample,
    utcnow,
)
from app.store.session import create_db_engine, init_db


@pytest.fixture
def engine(tmp_path) -> Engine:  # type: ignore[no-untyped-def]
    instance = create_db_engine(f"sqlite:///{tmp_path / 'alerts.db'}")
    init_db(instance)
    return instance


class FakeGates:
    """Stands in for the gate registry; alert rules must not need a broker."""

    def __init__(self, **kwargs: object) -> None:
        self._info = kwargs

    async def get(self, cluster: str) -> FakeGates:
        return self

    async def describe_cluster(self) -> object:
        class Info:
            under_replicated_partitions = 0
            offline_partitions = 0
            brokers: ClassVar[list[object]] = []

        info = Info()
        for name, value in self._info.items():
            setattr(info, name, value)
        return info


def seed_lag(engine: Engine, lags: list[int], group_id: str = "g", cluster: str = "c") -> None:
    now = utcnow()
    with Session(engine) as session:
        for index, lag in enumerate(lags):
            session.add(
                OffsetSample(
                    at=now - timedelta(seconds=30 * (len(lags) - 1 - index)),
                    cluster=cluster,
                    group_id=group_id,
                    topic="t",
                    partition=0,
                    lag=lag,
                )
            )
        session.commit()


def rule(**kwargs: object) -> AlertRule:
    defaults: dict[str, object] = {
        "name": "test",
        "cluster": "c",
        "kind": AlertKind.LAG_ABOVE,
        "threshold": 100.0,
        "group_id": "g",
        "for_seconds": 0,
    }
    defaults.update(kwargs)
    return AlertRule(**defaults)  # type: ignore[arg-type]


class TestRuleEvaluation:
    async def test_lag_above_breaches(self, engine: Engine) -> None:
        seed_lag(engine, [500])
        result = await evaluate_rule(rule(threshold=100.0), engine=engine, gates=FakeGates())
        assert result.breached
        assert result.value == 500.0

    async def test_lag_below_threshold_does_not_breach(self, engine: Engine) -> None:
        seed_lag(engine, [50])
        result = await evaluate_rule(rule(threshold=100.0), engine=engine, gates=FakeGates())
        assert not result.breached

    async def test_lag_velocity_breaches_when_growing(self, engine: Engine) -> None:
        seed_lag(engine, [100, 400, 700, 1000])
        result = await evaluate_rule(
            rule(kind=AlertKind.LAG_VELOCITY, threshold=1.0), engine=engine, gates=FakeGates()
        )
        assert result.breached

    async def test_lag_velocity_quiet_when_catching_up(self, engine: Engine) -> None:
        seed_lag(engine, [1000, 700, 400, 100])
        result = await evaluate_rule(
            rule(kind=AlertKind.LAG_VELOCITY, threshold=1.0), engine=engine, gates=FakeGates()
        )
        assert not result.breached

    async def test_under_replicated(self, engine: Engine) -> None:
        result = await evaluate_rule(
            rule(kind=AlertKind.UNDER_REPLICATED, threshold=0.0, group_id=None),
            engine=engine,
            gates=FakeGates(under_replicated_partitions=3),
        )
        assert result.breached
        assert result.value == 3.0

    async def test_broker_down_when_fewer_than_expected(self, engine: Engine) -> None:
        result = await evaluate_rule(
            rule(kind=AlertKind.BROKER_DOWN, threshold=3.0, group_id=None),
            engine=engine,
            gates=FakeGates(brokers=[object(), object()]),
        )
        assert result.breached
        assert result.value == 2.0

    async def test_broker_down_quiet_when_all_present(self, engine: Engine) -> None:
        result = await evaluate_rule(
            rule(kind=AlertKind.BROKER_DOWN, threshold=3.0, group_id=None),
            engine=engine,
            gates=FakeGates(brokers=[object(), object(), object()]),
        )
        assert not result.breached

    async def test_rule_without_a_group_is_not_a_breach(self, engine: Engine) -> None:
        # Better to report nothing than to fire on a meaningless comparison.
        result = await evaluate_rule(rule(group_id=None), engine=engine, gates=FakeGates())
        assert not result.breached

    async def test_no_samples_is_not_a_breach(self, engine: Engine) -> None:
        result = await evaluate_rule(
            rule(kind=AlertKind.LAG_VELOCITY), engine=engine, gates=FakeGates()
        )
        assert not result.breached


class TestEvaluatorLifecycle:
    def _evaluator(self, engine: Engine, gates: object) -> AlertEvaluator:
        return AlertEvaluator(engine, gates, None, None)  # type: ignore[arg-type]

    async def test_fires_and_records_history(self, engine: Engine) -> None:
        seed_lag(engine, [500])
        with Session(engine) as session:
            session.add(rule(for_seconds=0))
            session.commit()

        transitions = await self._evaluator(engine, FakeGates()).evaluate_once()
        assert len(transitions) == 1
        assert transitions[0].state is AlertState.FIRING

        with Session(engine) as session:
            stored = session.exec(select(AlertRule)).one()
            assert stored.state is AlertState.FIRING
            assert stored.last_value == 500.0

    async def test_for_seconds_debounces(self, engine: Engine) -> None:
        """A breach must hold before firing, so one spike does not page."""
        seed_lag(engine, [500])
        with Session(engine) as session:
            session.add(rule(for_seconds=3600))
            session.commit()

        transitions = await self._evaluator(engine, FakeGates()).evaluate_once()
        assert transitions == []

        with Session(engine) as session:
            stored = session.exec(select(AlertRule)).one()
            # Still OK, but the clock has started.
            assert stored.state is AlertState.OK
            assert stored.since is not None

    async def test_fires_once_the_hold_has_elapsed(self, engine: Engine) -> None:
        seed_lag(engine, [500])
        with Session(engine) as session:
            stored = rule(for_seconds=60)
            stored.since = datetime.now(UTC) - timedelta(seconds=120)
            session.add(stored)
            session.commit()

        transitions = await self._evaluator(engine, FakeGates()).evaluate_once()
        assert len(transitions) == 1

    async def test_cooldown_prevents_repeat_notifications(self, engine: Engine) -> None:
        seed_lag(engine, [500])
        with Session(engine) as session:
            stored = rule(for_seconds=0, cooldown_seconds=3600)
            session.add(stored)
            session.commit()

        evaluator = self._evaluator(engine, FakeGates())
        first = await evaluator.evaluate_once()
        second = await evaluator.evaluate_once()
        assert len(first) == 1
        assert second == [], "cooldown should suppress the repeat"

    async def test_recovery_is_reported_once(self, engine: Engine) -> None:
        seed_lag(engine, [500])
        with Session(engine) as session:
            session.add(rule(for_seconds=0))
            session.commit()

        evaluator = self._evaluator(engine, FakeGates())
        await evaluator.evaluate_once()

        # Lag drops below the threshold.
        with Session(engine) as session:
            for sample in session.exec(select(OffsetSample)).all():
                sample.lag = 0
                session.add(sample)
            session.commit()

        recovery = await evaluator.evaluate_once()
        assert len(recovery) == 1
        assert recovery[0].state is AlertState.OK
        assert "recovered" in recovery[0].message

        # And it does not keep announcing the recovery.
        assert await evaluator.evaluate_once() == []

    async def test_disabled_rules_are_skipped(self, engine: Engine) -> None:
        seed_lag(engine, [500])
        with Session(engine) as session:
            session.add(rule(for_seconds=0, enabled=False))
            session.commit()
        assert await self._evaluator(engine, FakeGates()).evaluate_once() == []

    async def test_history_accumulates(self, engine: Engine) -> None:
        seed_lag(engine, [500])
        with Session(engine) as session:
            session.add(rule(for_seconds=0, cooldown_seconds=0))
            session.commit()

        evaluator = self._evaluator(engine, FakeGates())
        await evaluator.evaluate_once()
        await evaluator.evaluate_once()

        with Session(engine) as session:
            assert len(session.exec(select(AlertFiring)).all()) >= 2


class TestWebhookSigning:
    def test_signature_is_stable_and_verifiable(self) -> None:
        body = json.dumps({"rule": "test"}).encode()
        expected = sign(body, "shared-secret")
        assert sign(body, "shared-secret") == expected
        assert len(expected) == 64  # hex SHA-256

    def test_signature_changes_with_the_body(self) -> None:
        assert sign(b'{"a":1}', "s") != sign(b'{"a":2}', "s")

    def test_signature_changes_with_the_secret(self) -> None:
        assert sign(b'{"a":1}', "one") != sign(b'{"a":1}', "two")

    def test_header_name(self) -> None:
        assert SIGNATURE_HEADER == "X-KafkaPlay-Signature"


class TestNotifierConfiguration:
    def _settings(self, **kwargs: object) -> Settings:
        base: dict[str, object] = {
            "session_secret": "x" * 48,
            "database_url": "sqlite:///:memory:",
        }
        base.update(kwargs)
        return Settings(**base)  # type: ignore[arg-type]

    def test_reports_nothing_configured_by_default(self) -> None:
        assert not Notifier(self._settings()).any_configured

    def test_detects_a_configured_webhook(self) -> None:
        assert Notifier(self._settings(webhook_url="https://example.org/hook")).any_configured

    def test_detects_configured_smtp(self) -> None:
        assert Notifier(self._settings(smtp_host="smtp.example.org")).any_configured

    async def test_unconfigured_sinks_report_not_configured(self) -> None:
        notifier = Notifier(self._settings())
        firing = AlertFiring(
            rule_id=1,
            rule_name="r",
            cluster="c",
            severity=AlertSeverity.INFO,
            state=AlertState.FIRING,
            message="m",
        )
        results = await notifier.send_test(firing)
        assert set(results) == {"webhook", "slack", "teams", "email"}
        assert all(value == "not configured" for value in results.values())

    async def test_dispatch_survives_an_unreachable_sink(self) -> None:
        # A broken webhook must not stop alert evaluation.
        notifier = Notifier(self._settings(webhook_url="http://127.0.0.1:1/nope"))
        firing = AlertFiring(
            rule_id=1,
            rule_name="r",
            cluster="c",
            severity=AlertSeverity.CRITICAL,
            state=AlertState.FIRING,
            message="m",
        )
        await notifier.dispatch([firing])
        assert not firing.notified
        assert firing.notify_error
