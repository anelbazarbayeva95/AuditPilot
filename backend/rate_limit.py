"""Per-client rate limiting for the endpoints that start an audit.

An audit costs three headless Chromium runs and up to three Gemini calls, so
the limit is on *starting* audits, not on polling or reading results.

In-memory and per-process, like JobManager — enough for the single-container
deployment this backend runs as. A multi-replica deployment would need a
shared store (e.g. Redis) instead.

Client identity: behind a reverse proxy (Azure Container Apps ingress, a load
balancer) every request arrives from the proxy's address, so limiting on the
socket peer would put all visitors in one bucket. Set TRUSTED_PROXY_HOPS to
the number of proxies in front of the app and the client address is read from
X-Forwarded-For, counting from the right — the entries those proxies appended
themselves. Entries further left are client-supplied and trivially spoofed,
so they are never used. With the default of 0 the header is ignored entirely.
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import Callable, Optional

from fastapi import HTTPException, Request, status


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(int(os.environ.get(name, default)), minimum)
    except ValueError:
        return default


class SlidingWindowLimiter:
    """At most `max_events` per key within any `window_seconds` span."""

    def __init__(self, max_events: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = {}

    def hit(self, key: str) -> Optional[float]:
        """Records an event for `key`. Returns None if allowed, else seconds until it would be."""
        now = self._clock()
        cutoff = now - self.window_seconds
        self._sweep(cutoff)

        events = self._events.setdefault(key, deque())
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= self.max_events:
            return max(events[0] + self.window_seconds - now, 1.0)
        events.append(now)
        return None

    def _sweep(self, cutoff: float) -> None:
        # Drop keys whose newest event has aged out, so one-off visitors
        # don't accumulate forever.
        stale = [key for key, events in self._events.items() if not events or events[-1] <= cutoff]
        for key in stale:
            del self._events[key]


def _describe_window(seconds: float) -> str:
    if seconds % 3600 == 0:
        hours = int(seconds // 3600)
        return "hour" if hours == 1 else f"{hours} hours"
    minutes = max(round(seconds / 60), 1)
    return "minute" if minutes == 1 else f"{minutes} minutes"


def client_key(request: Request, trusted_hops: int) -> str:
    if trusted_hops > 0:
        forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
        if len(forwarded) >= trusted_hops:
            return forwarded[-trusted_hops]
    return request.client.host if request.client else "unknown"


AUDIT_RATE_LIMIT = _env_int("AUDIT_RATE_LIMIT", 10, minimum=1)
AUDIT_RATE_WINDOW_SECONDS = _env_int("AUDIT_RATE_WINDOW_SECONDS", 3600, minimum=1)
TRUSTED_PROXY_HOPS = _env_int("TRUSTED_PROXY_HOPS", 0)

audit_limiter = SlidingWindowLimiter(AUDIT_RATE_LIMIT, AUDIT_RATE_WINDOW_SECONDS)


async def limit_audit_starts(request: Request) -> None:
    """FastAPI dependency: 429 once a client exceeds the audit-start limit."""
    retry_after = audit_limiter.hit(client_key(request, TRUSTED_PROXY_HOPS))
    if retry_after is not None:
        minutes = max(round(retry_after / 60), 1)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many audits from this address — the limit is {audit_limiter.max_events} per "
                f"{_describe_window(audit_limiter.window_seconds)}. Try again in about {minutes} min."
            ),
            headers={"Retry-After": str(int(retry_after))},
        )
