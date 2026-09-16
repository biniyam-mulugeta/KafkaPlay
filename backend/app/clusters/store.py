"""Clusters added at runtime, stored in the database.

Three sources feed the registry, in increasing precedence:

1. ``KAFKA_BOOTSTRAP_SERVERS`` -- a one-line shortcut for the common
   single-cluster deployment.
2. Clusters added in the UI, stored here.
3. ``clusters.yaml`` -- a deliberate declaration that a redeploy reproduces,
   so it wins on a name collision.

Without this, a console started with no configuration would have no way to
reach a broker except by editing a file inside the container.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.clusters.models import (
    ClusterConfig,
    SaslConfig,
    SaslMechanism,
    SchemaRegistryConfig,
    SecurityProtocol,
    TlsConfig,
)
from app.logging import get_logger
from app.store.models import StoredCluster

log = get_logger(__name__)


def to_config(row: StoredCluster) -> ClusterConfig:
    """Turn a stored row into the same model the YAML loader produces."""
    protocol = SecurityProtocol(row.security_protocol)

    sasl = None
    if protocol in (SecurityProtocol.SASL_SSL, SecurityProtocol.SASL_PLAINTEXT):
        sasl = SaslConfig(
            mechanism=SaslMechanism(row.sasl_mechanism or "PLAIN"),
            username=row.sasl_username,
            password=row.sasl_password,
        )

    tls = None
    if protocol in (SecurityProtocol.SSL, SecurityProtocol.SASL_SSL):
        tls = TlsConfig(
            ca_location=row.tls_ca_location,
            insecure_skip_verify=row.tls_insecure_skip_verify,
        )

    registry = None
    if row.schema_registry_url:
        registry = SchemaRegistryConfig(
            url=row.schema_registry_url,
            username=row.schema_registry_username,
            password=row.schema_registry_password,
        )

    return ClusterConfig(
        name=row.name,
        label=row.label,
        bootstrap_servers=row.bootstrap_servers,
        security_protocol=protocol,
        sasl=sasl,
        tls=tls,
        schema_registry=registry,
        read_only=row.read_only,
        masking_enabled=row.masking_enabled,
    )


def load_stored(engine: Engine) -> list[ClusterConfig]:
    """Every cluster added through the UI."""
    with Session(engine) as session:
        rows = session.exec(select(StoredCluster)).all()

    configs: list[ClusterConfig] = []
    for row in rows:
        try:
            configs.append(to_config(row))
        except Exception as exc:
            # One bad row must not stop the console from starting.
            log.warning("stored_cluster_invalid", cluster=row.name, error=str(exc))
    return configs


def from_environment(bootstrap_servers: str, name: str) -> ClusterConfig:
    """The KAFKA_BOOTSTRAP_SERVERS shortcut."""
    return ClusterConfig(
        name=name,
        label=name,
        bootstrap_servers=bootstrap_servers,
        security_protocol=SecurityProtocol.PLAINTEXT,
    )
