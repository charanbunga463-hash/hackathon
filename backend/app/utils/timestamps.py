"""Timestamp helpers. All timestamps in API Doctor are UTC ISO-8601 strings."""

from __future__ import annotations

import time
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def monotonic_ms() -> float:
    return time.perf_counter() * 1000.0


def elapsed_ms(started_at: float) -> int:
    return int(round(monotonic_ms() - started_at))
