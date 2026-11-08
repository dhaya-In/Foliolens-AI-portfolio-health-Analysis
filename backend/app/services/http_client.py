"""Shared outbound HTTP helper with timeouts, bounded retries and normalised provider errors."""
from __future__ import annotations

import time

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class ProviderError(Exception):
    """kind: not_configured | auth | rate_limited | not_found | unavailable | bad_response"""

    def __init__(self, provider: str, kind: str, message: str):
        super().__init__(message)
        self.provider = provider
        self.kind = kind
        self.message = message

    def public(self) -> dict:
        return {"provider": self.provider, "kind": self.kind, "message": self.message}


def get_json(provider: str, url: str, params: dict, retries: int = 2, secret_params: tuple[str, ...] = ()) -> dict | list:
    """GET a JSON document. Retries only on network errors / 5xx / 429, with backoff.
    secret_params are never logged."""
    timeout = httpx.Timeout(get_settings().provider_timeout_seconds)
    last: ProviderError | None = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.get(url, params=params, timeout=timeout, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            last = ProviderError(provider, "unavailable", f"{provider} could not be reached ({type(exc).__name__}).")
        else:
            if resp.status_code in (401, 403):
                raise ProviderError(provider, "auth", f"{provider} rejected the API key (HTTP {resp.status_code}). Check that it is valid and not expired.")
            if resp.status_code == 404:
                raise ProviderError(provider, "not_found", f"{provider} has no data for this request.")
            if resp.status_code == 429:
                last = ProviderError(provider, "rate_limited", f"{provider} rate limit reached. Try again later.")
                retry_after = resp.headers.get("Retry-After", "")
                if attempt < retries and retry_after.isdigit() and int(retry_after) <= 5:
                    time.sleep(int(retry_after))
                    continue
            elif resp.status_code >= 500:
                last = ProviderError(provider, "unavailable", f"{provider} is having problems (HTTP {resp.status_code}).")
            elif resp.status_code >= 400:
                raise ProviderError(provider, "bad_response", f"{provider} returned HTTP {resp.status_code}.")
            else:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise ProviderError(provider, "bad_response", f"{provider} returned invalid JSON.") from exc
        log.warning("provider request failed", extra={"provider": provider, "error": last.kind if last else "?"})
        if attempt < retries:
            time.sleep(0.5 * (2 ** attempt))
    assert last is not None
    raise last
