"""Runtime concerns for multi-user, multi-worker operation.

Deliberately separate from `services/`: these modules know nothing about
projects or repairs, only about concurrency, identity, limits and observability.
"""

from .concurrency import cpu_bound, gather_bounded, io_bound, pool_stats, with_timeout
from .identity import ANONYMOUS_TENANT, AuthError, Principal, resolve_principal
from .jobs import JobConflict, JobQueue, JobRecord, JobRejected, JobStatus, QueueLimits
from .metrics import get_metrics
from .ratelimit import Rate, RateLimiter, get_rate_limiter
from .state import LockTimeout, MemoryStateBackend, StateBackend, get_state_backend

__all__ = [
    "ANONYMOUS_TENANT",
    "AuthError",
    "JobConflict",
    "JobQueue",
    "JobRecord",
    "JobRejected",
    "JobStatus",
    "LockTimeout",
    "MemoryStateBackend",
    "Principal",
    "QueueLimits",
    "Rate",
    "RateLimiter",
    "StateBackend",
    "cpu_bound",
    "gather_bounded",
    "get_metrics",
    "get_rate_limiter",
    "get_state_backend",
    "io_bound",
    "pool_stats",
    "resolve_principal",
    "with_timeout",
]
