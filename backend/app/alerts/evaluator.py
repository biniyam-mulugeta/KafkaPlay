"""Alert rule evaluation.

Rules are evaluated against the same data the charts use -- sampled offsets
and cluster metadata -- so alerting needs no Prometheus either.

Two behaviours that keep this from becoming noise:

* ``for_seconds``: a condition must hold continuously before the rule fires,
  so one noisy sample does not page anyone.
* ``cooldown_seconds``: while a rule stays firing, notifications are spaced
  out rather than repeated every evaluation.

Recovery is notified exactly once, because "it stopped" is as useful to know
as "it started".
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from app.clusters.registry import ClusterRegistry
from app.kafka.errors import KafkaGateError
from app.kafka.gates import GateRegistry
from app.logging import get_logger
from app.sampler.series import lag_history, topic_throughput
from app.store.models import (
    AlertFiring,
    AlertKind,
    AlertRule,
    AlertState,
    utcnow,
)

log = get_logger(__name__)


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalise a stored timestamp to an aware UTC datetime.

    SQLite has no timezone type, so a datetime written as aware comes back
    naive. Subtracting it from an aware "now" raises TypeError, which would
    break the debounce the first time a rule spanned two evaluation passes.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class Evaluation:
    """The outcome of testing one rule."""

    def __init__(self, breached: bool, value: float | None, message: str) -> None:
        self.breached = breached
        self.value = value
        self.message = message


async def evaluate_rule(
    rule: AlertRule,
    *,
    engine: Engine,
    gates: GateRegistry,
) -> Evaluation:
    """Test a single rule. Never raises; an unreadable cluster is not a breach.

    The match below is exhaustive over AlertKind and deliberately has no
    wildcard arm, so adding a kind without handling it is a type error
    rather than a rule that silently never fires.
    """
    try:
        match rule.kind:
            case AlertKind.LAG_ABOVE:
                if not rule.group_id:
                    return Evaluation(False, None, "rule has no consumer group")
                history = lag_history(
                    engine,
                    cluster=rule.cluster,
                    group_id=rule.group_id,
                    topic=rule.topic,
                    window_minutes=15,
                )
                value = float(history.current_lag or 0)
                return Evaluation(
                    value > rule.threshold,
                    value,
                    f"lag for {rule.group_id} is {int(value):,} "
                    f"(threshold {int(rule.threshold):,})",
                )

            case AlertKind.LAG_VELOCITY:
                if not rule.group_id:
                    return Evaluation(False, None, "rule has no consumer group")
                history = lag_history(
                    engine,
                    cluster=rule.cluster,
                    group_id=rule.group_id,
                    topic=rule.topic,
                    window_minutes=30,
                )
                velocity = history.lag_velocity
                if velocity is None:
                    return Evaluation(False, None, "not enough samples yet")
                return Evaluation(
                    velocity > rule.threshold,
                    velocity,
                    f"{rule.group_id} is falling behind at {velocity:.1f} messages/second",
                )

            case AlertKind.UNDER_REPLICATED:
                gate = await gates.get(rule.cluster)
                info = await gate.describe_cluster()
                value = float(info.under_replicated_partitions)
                return Evaluation(
                    value > rule.threshold,
                    value,
                    f"{int(value)} under-replicated partition(s)",
                )

            case AlertKind.OFFLINE_PARTITIONS:
                gate = await gates.get(rule.cluster)
                info = await gate.describe_cluster()
                value = float(info.offline_partitions)
                return Evaluation(
                    value > rule.threshold, value, f"{int(value)} offline partition(s)"
                )

            case AlertKind.BROKER_DOWN:
                gate = await gates.get(rule.cluster)
                info = await gate.describe_cluster()
                value = float(len(info.brokers))
                # threshold is the expected broker count.
                return Evaluation(
                    value < rule.threshold,
                    value,
                    f"{int(value)} broker(s) visible, expected {int(rule.threshold)}",
                )

            case AlertKind.THROUGHPUT_ZERO:
                if not rule.topic:
                    return Evaluation(False, None, "rule has no topic")
                throughput = topic_throughput(
                    engine, cluster=rule.cluster, topic=rule.topic, window_minutes=15
                )
                if not throughput.points:
                    return Evaluation(False, None, "not enough samples yet")
                value = throughput.average or 0.0
                return Evaluation(
                    value <= rule.threshold,
                    value,
                    f"{rule.topic} is producing {value:.2f} messages/second",
                )

    except KafkaGateError as exc:
        # An unreachable cluster is its own problem; do not convert it into a
        # false breach of an unrelated rule.
        log.debug("alert_eval_degraded", rule=rule.name, error=exc.message)
        return Evaluation(False, None, f"cluster unreadable: {exc.message}")
    except Exception as exc:
        log.warning("alert_eval_failed", rule=rule.name, error=str(exc))
        return Evaluation(False, None, f"evaluation failed: {exc}")


class AlertEvaluator:
    def __init__(
        self,
        engine: Engine,
        gates: GateRegistry,
        clusters: ClusterRegistry,
        notifier: Notifier | None = None,
        *,
        interval_seconds: int = 30,
    ) -> None:
        self._engine = engine
        self._gates = gates
        self._clusters = clusters
        self._notifier = notifier
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_run_at: datetime | None = None

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="alert-evaluator")
            log.info("alert_evaluator_started", interval_seconds=self._interval)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.evaluate_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("alert_pass_failed", error=str(exc))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)

    async def evaluate_once(self) -> list[AlertFiring]:
        """One pass over every enabled rule. Returns state changes."""
        now = utcnow()
        transitions: list[AlertFiring] = []

        with Session(self._engine) as session:
            rules = list(session.exec(select(AlertRule).where(col(AlertRule.enabled))).all())

        for rule in rules:
            result = await evaluate_rule(rule, engine=self._engine, gates=self._gates)
            pending: list[AlertFiring] = []

            with Session(self._engine) as session:
                fresh = session.get(AlertRule, rule.id)
                if fresh is None:
                    continue

                fresh.last_value = result.value

                if result.breached:
                    if fresh.state is AlertState.OK:
                        # Start the clock; do not fire until it has held.
                        if fresh.since is None:
                            fresh.since = now
                        since = _as_utc(fresh.since) or now
                        held = (now - since).total_seconds()
                        if held >= fresh.for_seconds:
                            fresh.state = AlertState.FIRING
                            firing = AlertFiring(
                                rule_id=fresh.id or 0,
                                rule_name=fresh.name,
                                cluster=fresh.cluster,
                                severity=fresh.severity,
                                state=AlertState.FIRING,
                                value=result.value,
                                message=result.message,
                            )
                            session.add(firing)
                            pending.append(firing)
                            fresh.last_notified_at = now
                    else:
                        # Already firing: re-notify only after the cooldown.
                        last = _as_utc(fresh.last_notified_at)
                        due = last is None or (now - last).total_seconds() >= fresh.cooldown_seconds
                        if due:
                            firing = AlertFiring(
                                rule_id=fresh.id or 0,
                                rule_name=fresh.name,
                                cluster=fresh.cluster,
                                severity=fresh.severity,
                                state=AlertState.FIRING,
                                value=result.value,
                                message=result.message,
                            )
                            session.add(firing)
                            pending.append(firing)
                            fresh.last_notified_at = now
                else:
                    if fresh.state is AlertState.FIRING:
                        fresh.state = AlertState.OK
                        recovery = AlertFiring(
                            rule_id=fresh.id or 0,
                            rule_name=fresh.name,
                            cluster=fresh.cluster,
                            severity=fresh.severity,
                            state=AlertState.OK,
                            value=result.value,
                            message=f"recovered: {result.message}",
                        )
                        session.add(recovery)
                        pending.append(recovery)
                    fresh.since = None

                session.add(fresh)
                session.commit()

                # Load every attribute and detach, so the notifier can read
                # these after the session closes without a lazy-load error.
                for firing in pending:
                    session.refresh(firing)
                    session.expunge(firing)
                transitions.extend(pending)

        self.last_run_at = now

        if self._notifier is not None and transitions:
            await self._notifier.dispatch(transitions)
            # dispatch() records delivery outcome on each object; persist it,
            # or a failed notification would leave no trace.
            with Session(self._engine) as session:
                for firing in transitions:
                    stored = session.get(AlertFiring, firing.id)
                    if stored is not None:
                        stored.notified = firing.notified
                        stored.notify_error = firing.notify_error
                        session.add(stored)
                session.commit()

        self._prune()
        return transitions

    def _prune(self, keep_days: int = 90) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=keep_days)
        with Session(self._engine) as session:
            stale = session.exec(select(AlertFiring).where(col(AlertFiring.at) < cutoff)).all()
            for row in stale:
                session.delete(row)
            session.commit()


# Imported late to avoid a circular import at module load.
from app.alerts.notify import Notifier  # noqa: E402
