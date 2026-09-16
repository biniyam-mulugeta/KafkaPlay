"""Cluster definitions.

These models describe *any* Kafka cluster: self-hosted PLAINTEXT, mTLS,
SASL/SCRAM, Confluent Cloud, MSK with IAM, Redpanda, Event Hubs. Nothing here
assumes a topology, a naming scheme, or a particular deployment.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SecurityProtocol(StrEnum):
    PLAINTEXT = "PLAINTEXT"
    SSL = "SSL"
    SASL_PLAINTEXT = "SASL_PLAINTEXT"
    SASL_SSL = "SASL_SSL"


class SaslMechanism(StrEnum):
    PLAIN = "PLAIN"
    SCRAM_SHA_256 = "SCRAM-SHA-256"
    SCRAM_SHA_512 = "SCRAM-SHA-512"
    OAUTHBEARER = "OAUTHBEARER"
    AWS_MSK_IAM = "AWS_MSK_IAM"


class MaskPreset(StrEnum):
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    EMAIL = "email"
    CREDIT_CARD = "credit_card"
    JWT = "jwt"


class TlsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ca_location: str | None = Field(default=None, description="Path to a CA bundle (PEM).")
    certificate_location: str | None = Field(default=None, description="Client cert for mTLS.")
    key_location: str | None = Field(default=None, description="Client key for mTLS.")
    key_password: str | None = None
    # Off by default would be a footgun; operators must opt in per cluster.
    verify_hostname: bool = True
    insecure_skip_verify: bool = Field(
        default=False,
        description="Disables certificate verification. Development only.",
    )


class SaslConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mechanism: SaslMechanism = SaslMechanism.PLAIN
    username: str | None = None
    password: str | None = None
    # OAUTHBEARER / OIDC
    oauth_token_endpoint: str | None = None
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    oauth_scope: str | None = None
    oauth_extensions: dict[str, str] = Field(default_factory=dict)
    # AWS_MSK_IAM
    aws_region: str | None = None
    aws_profile: str | None = None

    @model_validator(mode="after")
    def _check_mechanism_requirements(self) -> SaslConfig:
        match self.mechanism:
            case SaslMechanism.PLAIN | SaslMechanism.SCRAM_SHA_256 | SaslMechanism.SCRAM_SHA_512:
                if not self.username or not self.password:
                    raise ValueError(f"sasl.{self.mechanism} requires username and password")
            case SaslMechanism.OAUTHBEARER:
                if not self.oauth_token_endpoint or not self.oauth_client_id:
                    raise ValueError(
                        "sasl.OAUTHBEARER requires oauth_token_endpoint and oauth_client_id"
                    )
            case SaslMechanism.AWS_MSK_IAM:
                if not self.aws_region:
                    raise ValueError("sasl.AWS_MSK_IAM requires aws_region")
        return self


class SchemaRegistryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    username: str | None = None
    password: str | None = None
    ca_location: str | None = None
    insecure_skip_verify: bool = False


class MaskRule(BaseModel):
    """One masking rule. Either a preset, or a custom regex, never both."""

    model_config = ConfigDict(extra="forbid")

    preset: MaskPreset | None = None
    pattern: str | None = Field(default=None, description="Custom regex.")
    # Restrict a rule to certain topics / JMESPath locations. Empty = everywhere.
    topics: list[str] = Field(default_factory=list, description="Topic name globs.")
    paths: list[str] = Field(default_factory=list, description="JMESPath expressions.")
    replacement: str | None = Field(
        default=None,
        description="Override the preset's replacement, e.g. '***'.",
    )

    @model_validator(mode="after")
    def _exactly_one_source(self) -> MaskRule:
        if bool(self.preset) == bool(self.pattern):
            raise ValueError("a mask rule needs exactly one of 'preset' or 'pattern'")
        return self


def _default_mask_rules() -> list[MaskRule]:
    """Masking is on by default, and defaults to the personal-data presets."""
    return [
        MaskRule(preset=MaskPreset.IPV4),
        MaskRule(preset=MaskPreset.IPV6),
        MaskRule(preset=MaskPreset.EMAIL),
        MaskRule(preset=MaskPreset.CREDIT_CARD),
        MaskRule(preset=MaskPreset.JWT),
    ]


class ClusterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Stable identifier used in URLs and the audit log.")
    label: str | None = Field(default=None, description="Human-facing name; defaults to `name`.")
    bootstrap_servers: str
    security_protocol: SecurityProtocol = SecurityProtocol.PLAINTEXT
    tls: TlsConfig | None = None
    sasl: SaslConfig | None = None
    schema_registry: SchemaRegistryConfig | None = None

    client_id: str = Field(default="kafkaplay")
    request_timeout_seconds: float | None = Field(default=None, gt=0)

    read_only: bool = Field(
        default=False,
        description="Per-cluster override; the global READ_ONLY flag still wins when set.",
    )
    masking_enabled: bool = True
    mask_rules: list[MaskRule] = Field(default_factory=_default_mask_rules)

    # Flow-map producer edges cannot be derived from the Kafka APIs. Operators
    # may declare them, and the UI merges these with anything JMX can supply.
    producer_hints: dict[str, list[str]] = Field(
        default_factory=dict,
        description="client_id -> topics it produces to.",
    )
    group_output_hints: dict[str, list[str]] = Field(
        default_factory=dict,
        description="consumer group -> topics it writes to.",
    )

    @property
    def display_name(self) -> str:
        return self.label or self.name

    @model_validator(mode="after")
    def _check_protocol_consistency(self) -> ClusterConfig:
        needs_sasl = self.security_protocol in (
            SecurityProtocol.SASL_PLAINTEXT,
            SecurityProtocol.SASL_SSL,
        )
        if needs_sasl and self.sasl is None:
            raise ValueError(f"security_protocol={self.security_protocol} requires a 'sasl' block")
        if not needs_sasl and self.sasl is not None:
            raise ValueError(
                f"security_protocol={self.security_protocol} does not use SASL; "
                "remove the 'sasl' block or switch to SASL_SSL/SASL_PLAINTEXT"
            )
        return self


class ClustersFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clusters: list[ClusterConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_names(self) -> ClustersFile:
        seen: set[str] = set()
        for cluster in self.clusters:
            if cluster.name in seen:
                raise ValueError(f"duplicate cluster name: {cluster.name!r}")
            seen.add(cluster.name)
        return self
