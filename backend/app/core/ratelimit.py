"""Small in-process sliding-window rate limiter.

Good for a single backend process. If you run several workers/instances, replace it
with a shared store (e.g. Redis) so limits are enforced across processes.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: int) -> int | None:
        """Record a hit. Returns None if allowed, otherwise seconds until retry."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return max(1, int(q[0] + window - now) + 1)
            q.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def parse_rule(rule: str) -> tuple[int, int]:
    count, _, seconds = rule.partition("/")
    return int(count), int(seconds or 60)


def client_ip(request: Request) -> str:
    # Only trust X-Forwarded-For when uvicorn runs with --proxy-headers behind your own proxy;
    # uvicorn then rewrites request.client for us, so we never parse the header ourselves.
    return request.client.host if request.client else "unknown"


def enforce(request: Request, bucket: str, rule: str, extra_key: str = "", include_ip: bool = True) -> None:
    limit, window = parse_rule(rule)
    ip = client_ip(request) if include_ip else "*"
    retry = limiter.check(f"{bucket}:{ip}:{extra_key}", limit, window)
    if retry is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait and try again.",
            headers={"Retry-After": str(retry)},
        )
