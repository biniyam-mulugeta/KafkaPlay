"""Short-TTL cache for admin reads.

The point is load, not latency: without it, five open browser tabs polling
every five seconds would multiply broker traffic by five. With it they share
one in-flight call.

Single-flight matters as much as the TTL. When several requests miss the same
key at once, exactly one goes to the broker and the rest await its result.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(slots=True)
class _Entry[T]:
    value: T
    expires_at: float


class TTLCache:
    """Async cache with per-key single-flight."""

    def __init__(self, ttl_seconds: float, *, max_entries: int = 2048) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._entries: dict[str, _Entry[object]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    def _now(self) -> float:
        return time.monotonic()

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    def _evict_if_needed(self) -> None:
        if len(self._entries) <= self._max_entries:
            return
        # Cheap and adequate: drop whatever expires soonest.
        oldest = sorted(self._entries.items(), key=lambda item: item[1].expires_at)
        for key, _ in oldest[: len(self._entries) - self._max_entries]:
            self._entries.pop(key, None)
            self._locks.pop(key, None)

    def peek(self, key: str) -> object | None:
        entry = self._entries.get(key)
        if entry is None or entry.expires_at <= self._now():
            return None
        return entry.value

    async def get_or_load[T](self, key: str, loader: Callable[[], Awaitable[T]]) -> T:
        """Return the cached value, or call ``loader`` exactly once."""
        if self._ttl <= 0:
            return await loader()

        cached = self.peek(key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        lock = await self._lock_for(key)
        async with lock:
            # Another waiter may have populated it while we queued.
            cached = self.peek(key)
            if cached is not None:
                return cached  # type: ignore[return-value]

            value = await loader()
            self._entries[key] = _Entry(value=value, expires_at=self._now() + self._ttl)
            self._evict_if_needed()
            return value

    def invalidate(self, key: str) -> None:
        self._entries.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        """Drop a whole family of keys, e.g. after a write to one cluster."""
        for key in [key for key in self._entries if key.startswith(prefix)]:
            self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
