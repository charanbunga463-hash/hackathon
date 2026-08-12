"""Measured comparison of the authenticated request path.

Not a pytest test — a harness. Run it directly:

    python -m tests.bench_hotpath

It counts what one authenticated request actually costs, because the claim
being checked is "fewer round trips", and that is a count, not an opinion:

  * `store_loads`   — reads of the user record (a Postgres query in production,
                      a file read locally). Was one per request.
  * `state_reads`   — GETs against the state backend (Redis in production).
  * `state_writes`  — SETs against it. Was one per request, purely to slide the
                      session's idle TTL forward.

`--legacy` restores the pre-refactor behaviour (uncached user read, unthrottled
session touch) so the two are measured by the same code on the same machine.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class Counters:
    def __init__(self) -> None:
        self.store_loads = 0
        self.state_reads = 0
        self.state_writes = 0

    def as_dict(self, requests: int) -> dict:
        return {
            "store_loads": self.store_loads,
            "state_reads": self.state_reads,
            "state_writes": self.state_writes,
            "per_request": {
                "store_loads": round(self.store_loads / requests, 3),
                "state_reads": round(self.state_reads / requests, 3),
                "state_writes": round(self.state_writes / requests, 3),
            },
        }


def run(requests: int, legacy: bool) -> tuple[dict, list[float]]:
    import tempfile

    from fastapi.testclient import TestClient

    from app.api import deps
    from app.config.settings import Settings, get_settings
    from app.main import app
    from app.runtime import state as state_module
    from app.services import (
        email_service,
        otp_service,
        repair_service,
        session_service,
        user_service as user_service_module,
    )
    from app.services.project_service import ProjectService

    from .test_auth import PASSWORD, CapturingSender

    tmp = Path(tempfile.mkdtemp(prefix="bench-"))
    configured = Settings(
        database_url=None,
        data_dir=tmp / "data",
        redis_url=None,
        execution_mode="local",
        openai_api_key=None,
        auth_mode="user",
        secret_key="k" * 48,
        rate_limit_enabled=False,
        otp_resend_cooldown_seconds=0,
    )
    configured.ensure_directories()

    get_settings.cache_clear()
    import app.config.settings as settings_module

    settings_module.get_settings = lambda: configured
    deps.get_settings = lambda: configured

    projects = ProjectService(configured)
    deps._project_service = lambda: projects
    for module in (repair_service, user_service_module, otp_service, session_service):
        getattr(module, f"reset_{module.__name__.rsplit('.', 1)[-1]}")()
    email_service.reset_email_service()
    mailbox = CapturingSender()
    email_service._service = email_service.EmailService(configured, mailbox)

    counters = Counters()

    # --- instrument the two layers whose round trips we are counting --------
    from app.services.user_service import JsonUserStore

    original_load = JsonUserStore.load

    def counted_load(self, user_id):
        counters.store_loads += 1
        return original_load(self, user_id)

    JsonUserStore.load = counted_load

    Memory = state_module.MemoryStateBackend
    original_get, original_set = Memory.get_json, Memory.set_json

    async def counted_get(self, key):
        if key.startswith("session:"):
            counters.state_reads += 1
        return await original_get(self, key)

    async def counted_set(self, key, value, *, ttl=None):
        if key.startswith("session:"):
            counters.state_writes += 1
        return await original_set(self, key, value, ttl=ttl)

    Memory.get_json, Memory.set_json = counted_get, counted_set

    if legacy:
        # The pre-refactor behaviour, for an apples-to-apples comparison.
        from app.services.session_service import SessionService
        from app.services.user_service import UserService

        async def uncached_get(self, user_id):
            return await self.get_async(user_id)

        UserService.get_cached_async = uncached_get

        async def always_touch(self, record):
            remaining = record.seconds_remaining
            if remaining <= 0:
                await self.revoke_hash(record.token_hash, user_id=record.user_id)
                return True
            ttl = min(self.settings.session_idle_timeout_seconds, remaining)
            payload = record.as_payload()
            payload["last_seen"] = time.time()
            await state_module.get_state_backend().set_json(
                self._key(record.token_hash), payload, ttl=ttl
            )
            return True

        SessionService.touch = always_touch

    app.dependency_overrides[deps.settings_dep] = lambda: configured
    app.dependency_overrides[deps.project_service] = lambda: projects

    latencies: list[float] = []
    with TestClient(app) as client:
        email = "bench@example.com"
        assert client.post(
            "/api/auth/register",
            json={"name": "Bench User", "email": email, "password": PASSWORD},
        ).status_code == 201
        code = mailbox.latest_code(email)
        assert client.post(
            "/api/auth/verify-otp", json={"email": email, "code": code}
        ).status_code == 200

        # Warm every lazy path so the first request does not dominate.
        for _ in range(5):
            client.get("/api/projects")

        counters.__init__()
        for _ in range(requests):
            started = time.perf_counter()
            response = client.get("/api/projects")
            latencies.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200, response.text

    app.dependency_overrides.clear()
    return counters.as_dict(requests), latencies


def report(label: str, counts: dict, latencies: list[float]) -> None:
    ordered = sorted(latencies)
    print(f"\n{label}")
    print("-" * len(label))
    print(f"  requests            {len(latencies)}")
    print(f"  user store reads    {counts['store_loads']:>6}  "
          f"({counts['per_request']['store_loads']}/request)")
    print(f"  state GETs          {counts['state_reads']:>6}  "
          f"({counts['per_request']['state_reads']}/request)")
    print(f"  state SETs          {counts['state_writes']:>6}  "
          f"({counts['per_request']['state_writes']}/request)")
    print(f"  median latency      {statistics.median(ordered):.3f} ms")
    print(f"  p95 latency         {ordered[int(len(ordered) * 0.95)]:.3f} ms")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--requests", type=int, default=200)
    parser.add_argument("--legacy", action="store_true")
    args = parser.parse_args()

    counts, latencies = run(args.requests, args.legacy)
    report("LEGACY (uncached user read, touch every request)" if args.legacy
           else "CURRENT (cached user read, throttled touch)", counts, latencies)


if __name__ == "__main__":
    main()
