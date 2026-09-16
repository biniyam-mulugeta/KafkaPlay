"""Per-cluster gate registry and the shared read cache.

One gate per cluster, created lazily and reused, so AdminClient connections
are not rebuilt per request. One cache shared across all clusters, keyed by
cluster name, so several browser tabs cost one broker call.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor

from app.clusters.models import ClusterConfig
from app.clusters.registry import ClusterRegistry
from app.kafka.cache import TTLCache
from app.kafka.errors import Degraded, KafkaGateError
from app.kafka.gate import KafkaGate
from app.logging import get_logger

log = get_logger(__name__)


class GateRegistry:
    def __init__(
        self,
        clusters: ClusterRegistry,
        *,
        timeout_seconds: float = 10.0,
        cache_ttl_seconds: float = 5.0,
        pool_size: int = 8,
    ) -> None:
        self._clusters = clusters
        self._timeout = timeout_seconds
        self._gates: dict[str, KafkaGate] = {}
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="kafka")
        self.cache = TTLCache(cache_ttl_seconds)

    async def get(self, cluster_name: str) -> KafkaGate:
        gate = self._gates.get(cluster_name)
        if gate is not None:
            return gate
        async with self._lock:
            gate = self._gates.get(cluster_name)
            if gate is None:
                cluster: ClusterConfig = self._clusters.get(cluster_name)
                gate = KafkaGate(
                    cluster,
                    timeout_seconds=self._timeout,
                    executor=self._executor,
                )
                self._gates[cluster_name] = gate
            return gate

    def invalidate(self, cluster_name: str) -> None:
        """Drop cached reads for a cluster after a write to it."""
        self.cache.invalidate_prefix(f"{cluster_name}:")

    def close(self) -> None:
        for gate in self._gates.values():
            gate.close()
        self._gates.clear()
        self._executor.shutdown(wait=False)


async def cached[T](
    gates: GateRegistry,
    cluster: str,
    key: str,
    loader: Callable[[], Awaitable[T]],
) -> T:
    return await gates.cache.get_or_load(f"{cluster}:{key}", loader)


async def degradable[T](
    factory: Callable[[], Awaitable[T]],
    *,
    fallback: T,
    context: str,
) -> tuple[T, Degraded | None]:
    """Run a read, converting broker failure into a degraded result.

    The caller still gets a well-formed response, and the UI shows a banner
    instead of an error page. This is what keeps one sick cluster from
    breaking a multi-cluster console.
    """
    try:
        return await factory(), None
    except KafkaGateError as exc:
        log.warning("kafka_degraded", context=context, reason=str(exc.reason), error=exc.message)
        return fallback, exc.to_degraded()
