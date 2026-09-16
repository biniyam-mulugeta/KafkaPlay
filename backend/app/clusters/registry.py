"""In-memory registry of configured clusters.

Multi-cluster from the start: every lookup is by cluster name, and there is no
"current" or "default" cluster anywhere in the backend. The UI picks one and
passes it explicitly.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from threading import RLock

from app.clusters.loader import load_clusters_file
from app.clusters.models import ClusterConfig


class UnknownClusterError(KeyError):
    def __init__(self, name: str, known: Iterable[str]) -> None:
        options = ", ".join(sorted(known)) or "none configured"
        super().__init__(f"unknown cluster {name!r}; configured clusters: {options}")
        self.name = name


class ClusterRegistry:
    """Thread-safe store of cluster definitions.

    Clusters come from ``clusters.yaml`` at startup and may be added or edited
    at runtime by an admin. Runtime edits are held here and persisted by the
    caller; this class deliberately knows nothing about the database.
    """

    def __init__(self, clusters: Iterable[ClusterConfig] = ()) -> None:
        self._lock = RLock()
        self._clusters: dict[str, ClusterConfig] = {c.name: c for c in clusters}

    @classmethod
    def from_file(cls, path: Path) -> ClusterRegistry:
        return cls(load_clusters_file(path).clusters)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._clusters)

    def list(self) -> list[ClusterConfig]:
        with self._lock:
            return [self._clusters[name] for name in sorted(self._clusters)]

    def get(self, name: str) -> ClusterConfig:
        with self._lock:
            try:
                return self._clusters[name]
            except KeyError:
                raise UnknownClusterError(name, self._clusters) from None

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._clusters

    def upsert(self, cluster: ClusterConfig) -> None:
        with self._lock:
            self._clusters[cluster.name] = cluster

    def remove(self, name: str) -> ClusterConfig:
        with self._lock:
            try:
                return self._clusters.pop(name)
            except KeyError:
                raise UnknownClusterError(name, self._clusters) from None

    def __len__(self) -> int:
        with self._lock:
            return len(self._clusters)

    @property
    def is_empty(self) -> bool:
        return len(self) == 0
