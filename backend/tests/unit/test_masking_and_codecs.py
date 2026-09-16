"""Masking, payload decoding, and the filter DSL."""

from __future__ import annotations

import json

import pytest

from app.clusters.models import MaskPreset, MaskRule
from app.codecs.decode import (
    PayloadFormat,
    decode_payload,
    framed_schema_id,
    looks_schema_framed,
)
from app.search.dsl import FilterError, MessageFilter, validate_filter
from app.security.masking import Masker, build_masker


def masker(*rules: MaskRule) -> Masker:
    return Masker(list(rules))


class TestIpMasking:
    def test_masks_ipv4_last_octet(self) -> None:
        result = masker(MaskRule(preset=MaskPreset.IPV4)).mask({"ip": "203.0.113.42"})
        assert result.value["ip"] == "203.0.113.xxx"
        assert result.applied

    def test_masks_ip_inside_free_text(self) -> None:
        result = masker(MaskRule(preset=MaskPreset.IPV4)).mask(
            {"log": "GET / from 198.51.100.7 ok"}
        )
        assert "198.51.100.xxx" in result.value["log"]
        assert "198.51.100.7 " not in result.value["log"]

    def test_leaves_non_addresses_alone(self) -> None:
        # Version numbers look like addresses but are not.
        result = masker(MaskRule(preset=MaskPreset.IPV4)).mask({"v": "999.888.777.666"})
        assert result.value["v"] == "999.888.777.666"

    def test_masks_nested_and_listed_values(self) -> None:
        result = masker(MaskRule(preset=MaskPreset.IPV4)).mask(
            {"a": {"b": ["203.0.113.1", "203.0.113.2"]}}
        )
        assert result.value["a"]["b"] == ["203.0.113.xxx", "203.0.113.xxx"]


class TestEmailAndCardMasking:
    def test_masks_email_keeping_first_letter_and_domain(self) -> None:
        result = masker(MaskRule(preset=MaskPreset.EMAIL)).mask({"e": "alice@example.org"})
        assert result.value["e"] == "a***@example.org"

    def test_masks_a_valid_card_number(self) -> None:
        # Luhn-valid test number.
        result = masker(MaskRule(preset=MaskPreset.CREDIT_CARD)).mask({"c": "4242424242424242"})
        assert result.value["c"].endswith("4242")
        assert result.value["c"].startswith("*")

    def test_leaves_luhn_invalid_digits_alone(self) -> None:
        # Order ids and timestamps must survive, or the browser is useless.
        result = masker(MaskRule(preset=MaskPreset.CREDIT_CARD)).mask({"id": "1234567890123456"})
        assert result.value["id"] == "1234567890123456"

    def test_masks_jwt(self) -> None:
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r"
        result = masker(MaskRule(preset=MaskPreset.JWT)).mask({"t": token})
        assert result.value["t"] == "eyJ***.***.***"


class TestMaskScoping:
    def test_topic_glob_limits_a_rule(self) -> None:
        rule = MaskRule(preset=MaskPreset.IPV4, topics=["access-*"])
        assert masker(rule).mask({"ip": "203.0.113.5"}, topic="access-log").applied
        assert not masker(rule).mask({"ip": "203.0.113.5"}, topic="orders").applied

    def test_custom_pattern_with_replacement(self) -> None:
        rule = MaskRule(pattern=r"ACC-\d{8}", replacement="ACC-********")
        result = masker(rule).mask({"account": "ACC-12345678"})
        assert result.value["account"] == "ACC-********"

    def test_invalid_regex_is_ignored_not_fatal(self) -> None:
        # A bad rule in config must not break message browsing entirely.
        instance = masker(MaskRule(pattern="([unclosed"), MaskRule(preset=MaskPreset.IPV4))
        result = instance.mask({"ip": "203.0.113.9"})
        assert result.value["ip"] == "203.0.113.xxx"

    def test_path_scoped_rule_only_touches_that_field(self) -> None:
        rule = MaskRule(preset=MaskPreset.IPV4, paths=["client_ip"])
        result = masker(rule).mask({"client_ip": "203.0.113.1", "server_ip": "203.0.113.2"})
        assert result.value["client_ip"] == "203.0.113.xxx"
        assert result.value["server_ip"] == "203.0.113.2"

    def test_original_payload_is_not_mutated(self) -> None:
        original = {"ip": "203.0.113.1"}
        masker(MaskRule(preset=MaskPreset.IPV4)).mask(original)
        assert original["ip"] == "203.0.113.1"


class TestMaskToggles:
    def test_disabled_globally(self) -> None:
        instance = build_masker(
            [MaskRule(preset=MaskPreset.IPV4)], cluster_enabled=True, global_enabled=False
        )
        assert not instance.enabled
        assert instance.mask({"ip": "203.0.113.1"}).value["ip"] == "203.0.113.1"

    def test_disabled_per_cluster(self) -> None:
        instance = build_masker(
            [MaskRule(preset=MaskPreset.IPV4)], cluster_enabled=False, global_enabled=True
        )
        assert not instance.enabled

    def test_enabled_when_both_on(self) -> None:
        instance = build_masker(
            [MaskRule(preset=MaskPreset.IPV4)], cluster_enabled=True, global_enabled=True
        )
        assert instance.enabled


class TestDecoding:
    def test_json_object(self) -> None:
        decoded = decode_payload(json.dumps({"a": 1}).encode())
        assert decoded.format is PayloadFormat.JSON
        assert decoded.value == {"a": 1}

    def test_json_array(self) -> None:
        assert decode_payload(b"[1,2,3]").format is PayloadFormat.JSON

    def test_plain_text(self) -> None:
        decoded = decode_payload(b"INFO request handled")
        assert decoded.format is PayloadFormat.TEXT
        assert decoded.value == "INFO request handled"

    def test_bare_number_is_text_not_json(self) -> None:
        # Valid JSON, but far more useful shown as the text it almost certainly is.
        assert decode_payload(b"42").format is PayloadFormat.TEXT

    def test_binary_falls_back_to_hex(self) -> None:
        decoded = decode_payload(b"\x00\x01\x02\xff\xfe")
        assert decoded.format is PayloadFormat.BINARY
        assert "00 01 02" in decoded.value

    def test_null_payload(self) -> None:
        decoded = decode_payload(None)
        assert decoded.format is PayloadFormat.NULL
        assert decoded.value is None

    def test_empty_payload(self) -> None:
        assert decode_payload(b"").format is PayloadFormat.TEXT

    def test_size_is_reported(self) -> None:
        assert decode_payload(b"hello").size_bytes == 5

    def test_hex_view_is_truncated(self) -> None:
        decoded = decode_payload(bytes(range(256)) * 20)
        assert "bytes)" in decoded.value

    def test_invalid_json_is_text(self) -> None:
        assert decode_payload(b'{"broken": ').format is PayloadFormat.TEXT


class TestSchemaFraming:
    def _framed(self, schema_id: int) -> bytes:
        return b"\x00" + schema_id.to_bytes(4, "big") + b"payloadbytes"

    def test_detects_confluent_framing(self) -> None:
        assert looks_schema_framed(self._framed(42))
        assert framed_schema_id(self._framed(42)) == 42

    def test_plain_json_is_not_framed(self) -> None:
        assert not looks_schema_framed(b'{"a":1}')
        assert framed_schema_id(b'{"a":1}') is None

    def test_framed_without_registry_reports_schema_id_and_reason(self) -> None:
        decoded = decode_payload(self._framed(7))
        assert decoded.format is PayloadFormat.BINARY
        assert decoded.schema_id == 7
        assert decoded.error and "Schema Registry" in decoded.error

    def test_framed_with_decoder(self) -> None:
        class FakeDecoder:
            def decode(self, data: bytes, schema_id: int) -> tuple[object, PayloadFormat]:
                return {"decoded": schema_id}, PayloadFormat.AVRO

        decoded = decode_payload(self._framed(9), schema_decoder=FakeDecoder())
        assert decoded.format is PayloadFormat.AVRO
        assert decoded.value == {"decoded": 9}

    def test_decoder_failure_falls_back_to_hex_with_reason(self) -> None:
        class BrokenDecoder:
            def decode(self, data: bytes, schema_id: int) -> tuple[object, PayloadFormat]:
                raise ValueError("schema 9 not found")

        decoded = decode_payload(self._framed(9), schema_decoder=BrokenDecoder())
        assert decoded.format is PayloadFormat.BINARY
        assert decoded.error and "not found" in decoded.error


class TestFilterDsl:
    def record(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "key": "cust-001",
            "value": {"status": "failed", "amount_cents": 25000, "path": "/admin/login"},
            "headers": {"source": "gateway"},
            "topic": "orders",
            "partition": 3,
            "offset": 99,
            "timestamp": 1758000000000,
        }
        base.update(overrides)
        return base

    def test_equality(self) -> None:
        assert MessageFilter.compile("value.status == 'failed'").matches(self.record())

    def test_non_match(self) -> None:
        assert not MessageFilter.compile("value.status == 'ok'").matches(self.record())

    def test_numeric_comparison(self) -> None:
        assert MessageFilter.compile("value.amount_cents > `10000`").matches(self.record())
        assert not MessageFilter.compile("value.amount_cents > `99999`").matches(self.record())

    def test_contains_function(self) -> None:
        assert MessageFilter.compile("contains(value.path, '/admin')").matches(self.record())

    def test_boolean_and(self) -> None:
        expression = "value.status == 'failed' && value.amount_cents > `1000`"
        assert MessageFilter.compile(expression).matches(self.record())

    def test_header_access(self) -> None:
        assert MessageFilter.compile("headers.source == 'gateway'").matches(self.record())

    def test_metadata_access(self) -> None:
        assert MessageFilter.compile("partition == `3`").matches(self.record())

    def test_missing_field_is_no_match_not_an_error(self) -> None:
        # Real topics hold heterogeneous records; one odd shape must not abort
        # the whole scan.
        assert not MessageFilter.compile("value.nonexistent == 'x'").matches(self.record())

    def test_type_mismatch_is_no_match(self) -> None:
        assert not MessageFilter.compile("value.status > `5`").matches(self.record())

    def test_invalid_expression_rejected_at_compile(self) -> None:
        with pytest.raises(FilterError):
            MessageFilter.compile("this is not ][ valid")

    def test_empty_expression_rejected(self) -> None:
        with pytest.raises(FilterError):
            MessageFilter.compile("   ")

    def test_validate_helper(self) -> None:
        assert validate_filter("value.a == 'b'") is None
        assert validate_filter("][") is not None
