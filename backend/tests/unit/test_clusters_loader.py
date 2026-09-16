from __future__ import annotations

import pytest

from app.clusters.loader import ClusterConfigError, parse_clusters, substitute_env
from app.clusters.models import SaslMechanism, SecurityProtocol


class TestSubstituteEnv:
    def test_replaces_known_variable(self) -> None:
        assert substitute_env("pw=${SECRET}", {"SECRET": "hunter2"}) == "pw=hunter2"

    def test_uses_default_when_missing(self) -> None:
        assert substitute_env("x=${NOPE:-fallback}", {}) == "x=fallback"

    def test_prefers_env_over_default(self) -> None:
        assert substitute_env("x=${A:-fallback}", {"A": "real"}) == "x=real"

    def test_escaped_form_is_literal(self) -> None:
        assert substitute_env("literal $${NOT_A_VAR}", {}) == "literal ${NOT_A_VAR}"

    def test_reports_every_missing_variable_at_once(self) -> None:
        with pytest.raises(ClusterConfigError) as exc:
            substitute_env("${ONE} ${TWO} ${ONE}", {})
        message = str(exc.value)
        assert "ONE" in message
        assert "TWO" in message

    def test_empty_default_is_allowed(self) -> None:
        assert substitute_env("x=${MISSING:-}", {}) == "x="


class TestParseClusters:
    def test_empty_file_yields_no_clusters(self) -> None:
        assert parse_clusters("", {}).clusters == []

    def test_minimal_plaintext_cluster(self) -> None:
        parsed = parse_clusters(
            """
            clusters:
              - name: local
                bootstrap_servers: broker:9092
            """,
            {},
        )
        assert len(parsed.clusters) == 1
        cluster = parsed.clusters[0]
        assert cluster.name == "local"
        assert cluster.security_protocol is SecurityProtocol.PLAINTEXT
        # Masking is on by default, with the personal-data presets loaded.
        assert cluster.masking_enabled
        assert len(cluster.mask_rules) == 5

    def test_sasl_cluster_with_env_substitution(self) -> None:
        parsed = parse_clusters(
            """
            clusters:
              - name: cloud
                bootstrap_servers: pkc.example.com:9092
                security_protocol: SASL_SSL
                sasl:
                  mechanism: SCRAM-SHA-512
                  username: ${KAFKA_USER}
                  password: ${KAFKA_PASSWORD}
            """,
            {"KAFKA_USER": "svc", "KAFKA_PASSWORD": "s3cret"},
        )
        sasl = parsed.clusters[0].sasl
        assert sasl is not None
        assert sasl.mechanism is SaslMechanism.SCRAM_SHA_512
        assert sasl.username == "svc"
        assert sasl.password == "s3cret"

    def test_sasl_protocol_without_sasl_block_is_rejected(self) -> None:
        with pytest.raises(ClusterConfigError, match="requires a 'sasl' block"):
            parse_clusters(
                """
                clusters:
                  - name: broken
                    bootstrap_servers: host:9092
                    security_protocol: SASL_SSL
                """,
                {},
            )

    def test_sasl_block_without_sasl_protocol_is_rejected(self) -> None:
        with pytest.raises(ClusterConfigError, match="does not use SASL"):
            parse_clusters(
                """
                clusters:
                  - name: broken
                    bootstrap_servers: host:9092
                    security_protocol: PLAINTEXT
                    sasl:
                      mechanism: PLAIN
                      username: u
                      password: p
                """,
                {},
            )

    def test_scram_without_credentials_is_rejected(self) -> None:
        with pytest.raises(ClusterConfigError, match="requires username and password"):
            parse_clusters(
                """
                clusters:
                  - name: broken
                    bootstrap_servers: host:9092
                    security_protocol: SASL_SSL
                    sasl:
                      mechanism: SCRAM-SHA-256
                """,
                {},
            )

    def test_msk_iam_requires_region(self) -> None:
        with pytest.raises(ClusterConfigError, match="requires aws_region"):
            parse_clusters(
                """
                clusters:
                  - name: msk
                    bootstrap_servers: b-1.example.amazonaws.com:9098
                    security_protocol: SASL_SSL
                    sasl:
                      mechanism: AWS_MSK_IAM
                """,
                {},
            )

    def test_duplicate_names_are_rejected(self) -> None:
        with pytest.raises(ClusterConfigError, match="duplicate cluster name"):
            parse_clusters(
                """
                clusters:
                  - name: same
                    bootstrap_servers: a:9092
                  - name: same
                    bootstrap_servers: b:9092
                """,
                {},
            )

    def test_unknown_key_is_rejected(self) -> None:
        # extra="forbid" turns a typo into a startup error instead of a
        # setting that silently does nothing.
        with pytest.raises(ClusterConfigError):
            parse_clusters(
                """
                clusters:
                  - name: typo
                    bootstrap_servers: a:9092
                    bootstrapservers: a:9092
                """,
                {},
            )

    def test_non_mapping_root_is_rejected(self) -> None:
        with pytest.raises(ClusterConfigError, match="must be a mapping"):
            parse_clusters("- just\n- a\n- list\n", {})

    def test_invalid_yaml_is_reported(self) -> None:
        with pytest.raises(ClusterConfigError, match="not valid YAML"):
            parse_clusters("clusters: [unclosed\n", {})

    def test_mask_rule_needs_exactly_one_source(self) -> None:
        with pytest.raises(ClusterConfigError, match="exactly one"):
            parse_clusters(
                """
                clusters:
                  - name: c
                    bootstrap_servers: a:9092
                    mask_rules:
                      - preset: ipv4
                        pattern: "\\\\d+"
                """,
                {},
            )
