"""In-process TTL cache that remembers when each value was fetched.

Expired entries are kept (up to `keep_stale_seconds`) so that, when a provider is down,
we can return the last good value explicitly marked as stale instead of failing outright.
Only public market data is cached here - never user portfolios.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class CacheEntry:
    value: Any
    fetched_at: datetime
    stored_monotonic: float


class TTLCache:
    def __init__(self, keep_stale_seconds: int = 7 * 86400, max_items: int = 5000) -> None:
        self._data: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self.keep_stale_seconds = keep_stale_seconds
        self.max_items = max_items

    def get(self, key: str, ttl: int) -> tuple[CacheEntry | None, bool]:
        """Returns (entry, is_fresh)."""
        with self._lock:
            entry = self._data.get(key)
        if entry is None:
            return None, False
        age = time.monotonic() - entry.stored_monotonic
        if age > self.keep_stale_seconds:
            with self._lock:
                self._data.pop(key, None)
            return None, False
        return entry, age <= ttl

    def set(self, key: str, value: Any, fetched_at: datetime | None = None) -> CacheEntry:
        entry = CacheEntry(value, fetched_at or datetime.now(timezone.utc), time.monotonic())
        with self._lock:
            if len(self._data) >= self.max_items:
                oldest = min(self._data, key=lambda k: self._data[k].stored_monotonic)
                self._data.pop(oldest, None)
            self._data[key] = entry
        return entry

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


@dataclass
class CachedResult:
    value: Any
    fetched_at: datetime
    from_cache: bool
    stale: bool
    error: str | None = None


def cached_call(cache: TTLCache, key: str, ttl: int, fn: Callable[[], Any], force: bool = False) -> CachedResult:
    """Return a fresh cached value, or call fn(); on failure fall back to a stale value if any."""
    entry, fresh = cache.get(key, ttl)
    if entry is not None and fresh and not force:
        return CachedResult(entry.value, entry.fetched_at, True, False)
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 - provider errors are normalised by the caller
        if entry is not None:
            return CachedResult(entry.value, entry.fetched_at, True, True, error=str(exc))
        raise
    new = cache.set(key, value)
    return CachedResult(value, new.fetched_at, False, False)
