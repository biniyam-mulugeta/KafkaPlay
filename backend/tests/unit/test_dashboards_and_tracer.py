"""Dashboard panels and the latency tracer."""

from __future__ import annotations

import json

from app.codecs.decode import decode_payload
from app.dashboards.panels import PanelSpec, PanelType, StatOp, build_panel, extract
from app.search.scan import ScannedMessage
from app.tracer.join import TimestampSource, TraceRequest, correlate


def message(
    value: object,
    *,
    key: str | None = None,
    timestamp: int | None = 1_758_000_000_000,
    partition: int = 0,
    offset: int = 0,
    topic: str = "t",
) -> ScannedMessage:
    raw = json.dumps(value).encode() if not isinstance(value, str) else value.encode()
    return ScannedMessage(
        topic=topic,
        partition=partition,
        offset=offset,
        timestamp=timestamp,
        timestamp_type="create_time",
        key=decode_payload(key.encode() if key else None),
        value=decode_payload(raw),
        headers={},
    )


def spec(**kwargs: object) -> PanelSpec:
    defaults: dict[str, object] = {
        "id": "p1",
        "title": "Panel",
        "type": PanelType.STAT,
        "topic": "t",
    }
    defaults.update(kwargs)
    return PanelSpec(**defaults)  # type: ignore[arg-type]


def build(panel: PanelSpec, messages: list[ScannedMessage]):  # type: ignore[no-untyped-def]
    return build_panel(
        panel, messages, sampled=len(messages), elapsed_seconds=0.1, stop_reason="completed"
    )


class TestExtraction:
    def test_separates_numbers_from_labels(self) -> None:
        messages = [message({"n": 1.5}), message({"n": 2.5}), message({"s": "x"})]
        values = extract(messages, "value.n")
        assert values.numbers == [1.5, 2.5]
        assert values.labels == []

    def test_booleans_are_labels_not_numbers(self) -> None:
        # bool subclasses int; splitting on a boolean field should give two
        # buckets, not a numeric histogram.
        values = extract([message({"ok": True}), message({"ok": False})], "value.ok")
        assert sorted(values.labels) == ["false", "true"]
        assert values.numbers == []

    def test_invalid_expression_yields_nothing(self) -> None:
        assert extract([message({"a": 1})], "][").numbers == []

    def test_missing_field_is_skipped(self) -> None:
        assert extract([message({"a": 1})], "value.missing").numbers == []


class TestStatPanel:
    def test_count(self) -> None:
        result = build(spec(stat_op=StatOp.COUNT), [message({"n": 1})] * 5)
        assert result.stat == 5.0

    def test_sum(self) -> None:
        messages = [message({"n": 10}), message({"n": 20})]
        assert build(spec(extract="value.n", stat_op=StatOp.SUM), messages).stat == 30.0

    def test_avg(self) -> None:
        messages = [message({"n": 10}), message({"n": 20})]
        assert build(spec(extract="value.n", stat_op=StatOp.AVG), messages).stat == 15.0

    def test_min_and_max(self) -> None:
        messages = [message({"n": 3}), message({"n": 9}), message({"n": 5})]
        assert build(spec(extract="value.n", stat_op=StatOp.MIN), messages).stat == 3.0
        assert build(spec(extract="value.n", stat_op=StatOp.MAX), messages).stat == 9.0

    def test_p95(self) -> None:
        messages = [message({"n": i}) for i in range(100)]
        result = build(spec(extract="value.n", stat_op=StatOp.P95), messages)
        assert result.stat is not None and 90 <= result.stat <= 99

    def test_no_values_gives_none_not_zero(self) -> None:
        # Zero would be a lie; there is no average of nothing.
        assert build(spec(extract="value.missing", stat_op=StatOp.AVG), []).stat is None


class TestSplitAndTopN:
    def test_split_by_counts_labels(self) -> None:
        messages = [message({"r": "eu"})] * 3 + [message({"r": "us"})] * 2
        result = build(spec(type=PanelType.SPLIT_BY, extract="value.r"), messages)
        assert [(b.label, b.value) for b in result.buckets] == [("eu", 3.0), ("us", 2.0)]

    def test_top_n_limits_results(self) -> None:
        messages = [message({"r": f"r{i}"}) for i in range(20)]
        result = build(spec(type=PanelType.TOP_N, extract="value.r", top_n=5), messages)
        assert len(result.buckets) == 5

    def test_split_without_extract_reports_an_error(self) -> None:
        result = build(spec(type=PanelType.SPLIT_BY), [message({"a": 1})])
        assert result.error and "extract" in result.error


class TestHistogram:
    def test_buckets_span_the_range(self) -> None:
        messages = [message({"score": i / 100}) for i in range(101)]
        result = build(spec(type=PanelType.HISTOGRAM, extract="value.score", buckets=10), messages)
        assert len(result.buckets) == 10
        assert sum(bucket.value for bucket in result.buckets) == 101

    def test_thresholds_are_passed_through(self) -> None:
        messages = [message({"score": 0.5})]
        result = build(
            spec(type=PanelType.HISTOGRAM, extract="value.score", thresholds=[0.7]), messages
        )
        assert result.thresholds == [0.7]

    def test_identical_values_collapse_to_one_bucket(self) -> None:
        messages = [message({"n": 5})] * 4
        result = build(spec(type=PanelType.HISTOGRAM, extract="value.n"), messages)
        assert len(result.buckets) == 1
        assert result.buckets[0].value == 4.0

    def test_no_numbers_reports_an_error(self) -> None:
        result = build(spec(type=PanelType.HISTOGRAM, extract="value.s"), [message({"s": "x"})])
        assert result.error and "numeric" in result.error


class TestThroughputPanel:
    def test_builds_a_series(self) -> None:
        base = 1_758_000_000_000
        messages = [message({"i": i}, timestamp=base + i * 1000) for i in range(60)]
        result = build(spec(type=PanelType.THROUGHPUT), messages)
        assert result.series
        assert all("messages_per_second" in point for point in result.series)

    def test_too_few_points_gives_an_empty_series(self) -> None:
        assert build(spec(type=PanelType.THROUGHPUT), [message({"i": 1})]).series == []


class TestLatencyTracer:
    def request(self, **kwargs: object) -> TraceRequest:
        defaults: dict[str, object] = {
            "source_topic": "a",
            "target_topic": "b",
            "source_key": "value.id",
            "target_key": "value.id",
            "timestamp_source": TimestampSource.KAFKA,
        }
        defaults.update(kwargs)
        return TraceRequest(**defaults)  # type: ignore[arg-type]

    def test_matches_by_key_and_measures_delta(self) -> None:
        base = 1_758_000_000_000
        source = [message({"id": "x"}, timestamp=base)]
        target = [message({"id": "x"}, timestamp=base + 250)]
        result = correlate(self.request(), source, target, source_scanned=1, target_scanned=1)
        assert result.matched == 1
        assert result.p50_ms == 250.0
        assert result.min_ms == 250.0

    def test_unmatched_targets_are_counted_not_hidden(self) -> None:
        """A low match rate must be visible, not silently flattering."""
        base = 1_758_000_000_000
        source = [message({"id": "x"}, timestamp=base)]
        target = [
            message({"id": "x"}, timestamp=base + 100),
            message({"id": "unknown"}, timestamp=base + 100),
        ]
        result = correlate(self.request(), source, target, source_scanned=1, target_scanned=2)
        assert result.matched == 1
        assert result.unmatched_target == 1

    def test_negative_deltas_are_reported_separately(self) -> None:
        # A target predating its source means a clock or key problem, not a
        # negative latency.
        base = 1_758_000_000_000
        source = [message({"id": "x"}, timestamp=base)]
        target = [message({"id": "x"}, timestamp=base - 500)]
        result = correlate(self.request(), source, target, source_scanned=1, target_scanned=1)
        assert result.matched == 0
        assert result.negative_count == 1

    def test_uses_the_earliest_source_for_a_repeated_key(self) -> None:
        base = 1_758_000_000_000
        source = [
            message({"id": "x"}, timestamp=base + 1000),
            message({"id": "x"}, timestamp=base),
        ]
        target = [message({"id": "x"}, timestamp=base + 1500)]
        result = correlate(self.request(), source, target, source_scanned=2, target_scanned=1)
        assert result.p50_ms == 1500.0

    def test_percentiles_are_ordered(self) -> None:
        base = 1_758_000_000_000
        source = [message({"id": str(i)}, timestamp=base) for i in range(100)]
        target = [message({"id": str(i)}, timestamp=base + i * 10) for i in range(100)]
        result = correlate(self.request(), source, target, source_scanned=100, target_scanned=100)
        assert result.p50_ms is not None and result.p95_ms is not None
        assert result.p50_ms <= result.p95_ms <= (result.p99_ms or result.p95_ms)

    def test_field_timestamps(self) -> None:
        source = [message({"id": "x", "t": 1_000_000})]
        target = [message({"id": "x", "t": 1_000_750})]
        result = correlate(
            self.request(
                timestamp_source=TimestampSource.FIELD,
                source_timestamp_field="value.t",
                target_timestamp_field="value.t",
            ),
            source,
            target,
            source_scanned=1,
            target_scanned=1,
        )
        assert result.matched == 1
        assert result.p50_ms == 750.0

    def test_invalid_key_expression_returns_empty(self) -> None:
        result = correlate(
            self.request(source_key="]["),
            [message({"id": "x"})],
            [],
            source_scanned=1,
            target_scanned=0,
        )
        assert result.matched == 0

    def test_buckets_are_long_tail_friendly(self) -> None:
        base = 1_758_000_000_000
        source = [message({"id": str(i)}, timestamp=base) for i in range(3)]
        target = [
            message({"id": "0"}, timestamp=base + 5),
            message({"id": "1"}, timestamp=base + 800),
            message({"id": "2"}, timestamp=base + 90_000),
        ]
        result = correlate(self.request(), source, target, source_scanned=3, target_scanned=3)
        assert result.matched == 3
        # Spread across low, middle and overflow buckets rather than all in one.
        assert len(result.buckets) == 3

    def test_result_is_labelled_an_estimate(self) -> None:
        assert (
            "estimate" in correlate(self.request(), [], [], source_scanned=0, target_scanned=0).note
        )
