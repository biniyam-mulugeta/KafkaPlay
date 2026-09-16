"""Unit tests for the Kafka access layer that need no broker."""

from __future__ import annotations

import asyncio

import pytest

from app.clusters.models import (
    ClusterConfig,
    SaslConfig,
    SaslMechanism,
    SecurityProtocol,
    TlsConfig,
)
from app.kafka.cache import TTLCache
from app.kafka.errors import (
    AuthenticationFailedError,
    BrokerTimeoutError,
    BrokerUnreachableError,
    DegradedReason,
    KafkaGateError,
    translate_kafka_error,
)
from app.kafka.gate import build_client_config, is_internal_topic
from app.kafka.gates import degradable
from app.kafka.models import PartitionInfo, PartitionLag


class TestInternalTopics:
    @pytest.mark.parametrize(
        "name", ["__consumer_offsets", "__transaction_state", "_schemas", "_confluent-metrics"]
    )
    def test_internal(self, name: str) -> None:
        assert is_internal_topic(name)

    @pytest.mark.parametrize("name", ["orders", "clickstream", "app-logs", "a_topic"])
    def test_not_internal(self, name: str) -> None:
        assert not is_internal_topic(name)


class TestClientConfig:
    def test_plaintext_minimal(self) -> None:
        config = build_client_config(ClusterConfig(name="c", bootstrap_servers="broker:9092"), 10.0)
        assert config["bootstrap.servers"] == "broker:9092"
        assert config["security.protocol"] == "PLAINTEXT"
        assert "sasl.username" not in config

    def test_scram_over_tls(self) -> None:
        cluster = ClusterConfig(
            name="c",
            bootstrap_servers="b:9093",
            security_protocol=SecurityProtocol.SASL_SSL,
            sasl=SaslConfig(mechanism=SaslMechanism.SCRAM_SHA_512, username="u", password="p"),
            tls=TlsConfig(ca_location="/certs/ca.pem"),
        )
        config = build_client_config(cluster, 10.0)
        assert config["security.protocol"] == "SASL_SSL"
        assert config["sasl.mechanism"] == "SCRAM-SHA-512"
        assert config["sasl.username"] == "u"
        assert config["ssl.ca.location"] == "/certs/ca.pem"

    def test_oauthbearer_maps_to_oidc(self) -> None:
        cluster = ClusterConfig(
            name="c",
            bootstrap_servers="b:9093",
            security_protocol=SecurityProtocol.SASL_SSL,
            sasl=SaslConfig(
                mechanism=SaslMechanism.OAUTHBEARER,
                oauth_token_endpoint="https://idp/token",
                oauth_client_id="client",
                oauth_client_secret="secret",
            ),
        )
        config = build_client_config(cluster, 10.0)
        assert config["sasl.oauthbearer.method"] == "oidc"
        assert config["sasl.oauthbearer.token.endpoint.url"] == "https://idp/token"

    def test_timeout_is_applied_in_milliseconds(self) -> None:
        config = build_client_config(ClusterConfig(name="c", bootstrap_servers="b:9092"), 7.5)
        assert config["socket.timeout.ms"] == 7500


class TestErrorTranslation:
    class _FakeError:
        def __init__(self, name: str) -> None:
            self._name = name

        def name(self) -> str:
            return self._name

        def __str__(self) -> str:
            return self._name

    def _exc(self, code: str) -> Exception:
        return Exception(self._FakeError(code))

    def test_timeout(self) -> None:
        assert isinstance(translate_kafka_error(self._exc("_TIMED_OUT")), BrokerTimeoutError)

    def test_transport_is_unreachable(self) -> None:
        assert isinstance(translate_kafka_error(self._exc("_TRANSPORT")), BrokerUnreachableError)

    def test_auth(self) -> None:
        assert isinstance(
            translate_kafka_error(self._exc("_AUTHENTICATION")), AuthenticationFailedError
        )

    def test_message_fallback_when_no_code(self) -> None:
        assert isinstance(
            translate_kafka_error(Exception("connection timed out")), BrokerTimeoutError
        )

    def test_passes_through_gate_errors(self) -> None:
        original = BrokerUnreachableError("already typed")
        assert translate_kafka_error(original) is original

    def test_degraded_carries_a_hint(self) -> None:
        degraded = BrokerUnreachableError("nope").to_degraded()
        assert degraded.reason is DegradedReason.UNREACHABLE
        assert degraded.hint and "advertised.listeners" in degraded.hint


class TestLagArithmetic:
    def test_normal_lag(self) -> None:
        lag = PartitionLag.build("t", 0, current_offset=100, high_watermark=150)
        assert lag.lag == 50

    def test_caught_up(self) -> None:
        assert PartitionLag.build("t", 0, current_offset=150, high_watermark=150).lag == 0

    def test_never_committed_is_unknown_not_negative(self) -> None:
        # A group with no commit reports -1; that must not become a lag of -1.
        assert PartitionLag.build("t", 0, current_offset=-1, high_watermark=150).lag is None

    def test_missing_watermark_is_unknown(self) -> None:
        assert PartitionLag.build("t", 0, current_offset=10, high_watermark=None).lag is None

    def test_committed_beyond_watermark_clamps_to_zero(self) -> None:
        # Can happen transiently; a negative lag would be nonsense in the UI.
        assert PartitionLag.build("t", 0, current_offset=200, high_watermark=150).lag == 0


class TestPartitionInfo:
    def test_under_replicated(self) -> None:
        assert PartitionInfo(
            partition=0, leader=1, replicas=[1, 2, 3], in_sync_replicas=[1, 2]
        ).is_under_replicated

    def test_fully_replicated(self) -> None:
        assert not PartitionInfo(
            partition=0, leader=1, replicas=[1, 2, 3], in_sync_replicas=[1, 2, 3]
        ).is_under_replicated

    def test_offline_when_no_leader(self) -> None:
        assert PartitionInfo(partition=0, leader=None, replicas=[1]).is_offline

    def test_message_count(self) -> None:
        info = PartitionInfo(partition=0, low_watermark=10, high_watermark=60)
        assert info.message_count == 50

    def test_message_count_unknown_without_watermarks(self) -> None:
        assert PartitionInfo(partition=0).message_count is None


class TestTTLCache:
    async def test_caches_within_ttl(self) -> None:
        cache = TTLCache(ttl_seconds=60)
        calls = 0

        async def loader() -> int:
            nonlocal calls
            calls += 1
            return calls

        assert await cache.get_or_load("k", loader) == 1
        assert await cache.get_or_load("k", loader) == 1
        assert calls == 1

    async def test_zero_ttl_disables_caching(self) -> None:
        cache = TTLCache(ttl_seconds=0)
        calls = 0

        async def loader() -> int:
            nonlocal calls
            calls += 1
            return calls

        await cache.get_or_load("k", loader)
        await cache.get_or_load("k", loader)
        assert calls == 2

    async def test_single_flight(self) -> None:
        """Concurrent misses must produce exactly one broker call.

        This is the property that stops N browser tabs multiplying load.
        """
        cache = TTLCache(ttl_seconds=60)
        calls = 0

        async def slow_loader() -> int:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return calls

        results = await asyncio.gather(*(cache.get_or_load("k", slow_loader) for _ in range(10)))
        assert calls == 1
        assert results == [1] * 10

    async def test_separate_keys_are_independent(self) -> None:
        cache = TTLCache(ttl_seconds=60)

        async def one() -> str:
            return "one"

        async def two() -> str:
            return "two"

        assert await cache.get_or_load("a", one) == "one"
        assert await cache.get_or_load("b", two) == "two"

    async def test_invalidate_prefix_scopes_to_one_cluster(self) -> None:
        cache = TTLCache(ttl_seconds=60)

        async def loader() -> str:
            return "v"

        await cache.get_or_load("prod:topics", loader)
        await cache.get_or_load("prod:groups", loader)
        await cache.get_or_load("staging:topics", loader)

        cache.invalidate_prefix("prod:")
        assert cache.peek("prod:topics") is None
        assert cache.peek("staging:topics") == "v"


class TestDegradable:
    async def test_returns_value_on_success(self) -> None:
        async def ok() -> str:
            return "fine"

        value, degraded = await degradable(ok, fallback="", context="test")
        assert value == "fine"
        assert degraded is None

    async def test_converts_failure_into_degraded(self) -> None:
        async def boom() -> str:
            raise BrokerUnreachableError("broker is down")

        value, degraded = await degradable(boom, fallback="fallback", context="test")
        assert value == "fallback"
        assert degraded is not None
        assert degraded.reason is DegradedReason.UNREACHABLE

    async def test_non_gate_errors_still_propagate(self) -> None:
        # A bug in our own code must not be silently reported as "degraded".
        async def bug() -> str:
            raise ValueError("programming error")

        with pytest.raises(ValueError):
            await degradable(bug, fallback="", context="test")

    async def test_gate_error_base_class_is_caught(self) -> None:
        async def boom() -> str:
            raise KafkaGateError("something broker-ish")

        _, degraded = await degradable(boom, fallback="", context="test")
        assert degraded is not None
