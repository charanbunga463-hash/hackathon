"""Per-identity rate limiting.

A token bucket, evaluated in the shared state backend so the limit is global
across workers rather than per-worker (four workers with a "60/min" limit each
is a 240/min limit, which is not the limit you configured).

Buckets are tiered by cost, because the endpoints are not equal:

  * `read`  — listings, status polls, dashboards. Generous.
  * `write` — uploads, imports, deletes. Moderate.
  * `heavy` — anything that starts a container or calls OpenAI. Tight.

Exceeding a limit returns 429 with `Retry-After`, never a silent drop.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .state import StateBackend, get_state_backend


@dataclass(frozen=True)
class Rate:
    capacity: int          # burst size
    per_seconds: float     # refill window for `capacity` tokens

    @property
    def refill_per_second(self) -> float:
        return self.capacity / self.per_seconds if self.per_seconds else float("inf")


DEFAULT_RATES: dict[str, Rate] = {
    "read": Rate(capacity=300, per_seconds=60),
    "write": Rate(capacity=30, per_seconds=60),
    "heavy": Rate(capacity=10, per_seconds=60),
}


@dataclass
class RateDecision:
    allowed: bool
    remaining: int
    retry_after: int
    limit: int

    def headers(self) -> dict[str, str]:
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
        }
        if not self.allowed:
            headers["Retry-After"] = str(self.retry_after)
        return headers


class RateLimiter:
    def __init__(
        self,
        rates: dict[str, Rate] | None = None,
        *,
        state: StateBackend | None = None,
        enabled: bool = True,
    ) -> None:
        self.rates = rates or dict(DEFAULT_RATES)
        self.state = state or get_state_backend()
        self.enabled = enabled

    async def check(self, tenant: str, bucket: str, cost: int = 1) -> RateDecision:
        rate = self.rates.get(bucket)
        if not self.enabled or rate is None:
            return RateDecision(True, remaining=10**6, retry_after=0, limit=0)

        key = f"rl:{bucket}:{tenant}"
        now = time.time()
        stored = await self.state.get_json(key)

        if isinstance(stored, dict):
            tokens = float(stored.get("tokens", rate.capacity))
            updated = float(stored.get("at", now))
        else:
            tokens, updated = float(rate.capacity), now

        # Refill for the time that has passed, capped at the burst size.
        elapsed = max(0.0, now - updated)
        tokens = min(float(rate.capacity), tokens + elapsed * rate.refill_per_second)

        if tokens >= cost:
            tokens -= cost
            await self.state.set_json(
                key, {"tokens": tokens, "at": now}, ttl=rate.per_seconds * 2
            )
            return RateDecision(
                True, remaining=int(tokens), retry_after=0, limit=rate.capacity
            )

        deficit = cost - tokens
        retry_after = max(1, math.ceil(deficit / rate.refill_per_second))
        await self.state.set_json(key, {"tokens": tokens, "at": now}, ttl=rate.per_seconds * 2)
        return RateDecision(
            False, remaining=0, retry_after=retry_after, limit=rate.capacity
        )


_limiter: RateLimiter | None = None


def init_rate_limiter(
    rates: dict[str, Rate] | None = None,
    *,
    state: StateBackend | None = None,
    enabled: bool = True,
) -> RateLimiter:
    global _limiter
    _limiter = RateLimiter(rates, state=state, enabled=enabled)
    return _limiter


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter


def reset_rate_limiter() -> None:
    global _limiter
    _limiter = None
