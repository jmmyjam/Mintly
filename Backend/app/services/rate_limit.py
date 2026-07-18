"""Per-IP request rate limiting (sliding window), as a FastAPI dependency.

Usage: `Depends(rate_limit("login", times=10, seconds=300))` on a route, or in
a router's `dependencies=[...]` to cover every route in it. Scopes are shared
by name — the cards and portfolio routers both use scope "api", so one client
draws from a single budget across both. Over-limit requests get a 429 with a
Retry-After header and a self-explaining detail message.

State is in-memory like the app's other caches: per-process, reset on restart.
That's the right weight for a single-worker deployment; a multi-worker deploy
would multiply every budget by the worker count (same caveat as _price_cache).

The client key is request.client.host. Behind a reverse proxy that would be
the proxy's address for everyone, so set RATE_LIMIT_TRUST_FORWARDED=1 there to
key on the first X-Forwarded-For hop instead — but never enable it without a
proxy, since the header is client-controlled (a spoofed one would let a single
abuser rotate through unlimited fake identities).
"""

import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

_TRUST_FORWARDED = os.getenv("RATE_LIMIT_TRUST_FORWARDED", "").lower() in ("1", "true", "yes")

_now = time.monotonic  # indirection so tests can fake the clock

_lock = threading.Lock()
_hits: dict[str, deque[float]] = {}          # "scope:ip" -> recent request times
_scopes: dict[str, tuple[int, int]] = {}     # scope -> (times, seconds), to catch mismatched reuse

# Old keys are pruned lazily on their own next request, so idle IPs would leak
# a small deque forever; sweep the whole table occasionally instead
_SWEEP_EVERY = 1000
_calls_until_sweep = _SWEEP_EVERY


def client_ip(request: Request) -> str:
    if _TRUST_FORWARDED:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _sweep(now: float) -> None:
    for key in list(_hits):
        window = _scopes[key.split(":", 1)[0]][1]
        hits = _hits[key]
        while hits and now - hits[0] >= window:
            hits.popleft()
        if not hits:
            del _hits[key]


def rate_limit(scope: str, times: int, seconds: int, what: str = "requests"):
    """Dependency allowing `times` requests per `seconds` per client, per scope."""
    registered = _scopes.setdefault(scope, (times, seconds))
    if registered != (times, seconds):
        raise ValueError(
            f"rate limit scope {scope!r} already registered with {registered}, got {(times, seconds)}"
        )

    def dependency(request: Request) -> None:
        global _calls_until_sweep
        key = f"{scope}:{client_ip(request)}"
        now = _now()
        with _lock:
            _calls_until_sweep -= 1
            if _calls_until_sweep <= 0:
                _calls_until_sweep = _SWEEP_EVERY
                _sweep(now)
            hits = _hits.setdefault(key, deque())
            while hits and now - hits[0] >= seconds:
                hits.popleft()
            if len(hits) >= times:
                retry = max(1, int(seconds - (now - hits[0])) + 1)
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many {what} — try again in about {retry} seconds",
                    headers={"Retry-After": str(retry)},
                )
            hits.append(now)

    return dependency


def reset() -> None:
    """Clear all counters (tests run many requests from one client)."""
    with _lock:
        _hits.clear()
