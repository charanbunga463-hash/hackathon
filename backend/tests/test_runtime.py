"""Tests for the production runtime: limits, isolation, and concurrency safety.

These target the properties that only break under load or with more than one
worker — exactly the failures that are invisible in a single-user demo.
"""

from __future__ import annotations

import asyncio

import pytest

from app.runtime.identity import AuthError, parse_api_keys, resolve_principal
from app.runtime.jobs import JobQueue, JobRejected, JobStatus, QueueLimits
from app.runtime.ratelimit import Rate, RateLimiter
from app.runtime.state import MemoryStateBackend

pytestmark = pytest.mark.asyncio


@pytest.fixture
def state() -> MemoryStateBackend:
    # No async setup needed, so a plain fixture avoids pytest-asyncio's
    # strict-mode async-generator handling.
    return MemoryStateBackend()


# ---------------------------------------------------------------- queue ----
async def test_global_concurrency_is_capped(state):
    """The whole point: N users must not mean N containers."""
    limits = QueueLimits(max_concurrent_global=2, max_concurrent_per_tenant=5, max_queued=100)
    queue = JobQueue(limits, state=state)

    peak = 0
    live = 0
    lock = asyncio.Lock()

    async def work() -> dict:
        nonlocal peak, live
        async with lock:
            live += 1
            peak = max(peak, live)
        await asyncio.sleep(0.05)
        async with lock:
            live -= 1
        return {}

    jobs = [
        await queue.submit(kind="execution", tenant=f"t{i}", key=f"p{i}", run=work)
        for i in range(12)
    ]
    await _drain(queue, jobs)

    assert peak <= 2, f"ran {peak} jobs concurrently despite a limit of 2"
    for job in jobs:
        record = await queue.get(job.id)
        assert record.status is JobStatus.SUCCEEDED


async def test_one_tenant_cannot_monopolise_the_pool(state):
    limits = QueueLimits(max_concurrent_global=4, max_concurrent_per_tenant=1, max_queued=100,
                         max_queued_per_tenant=50)
    queue = JobQueue(limits, state=state)

    peak = 0
    live = 0

    async def work() -> dict:
        nonlocal peak, live
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.03)
        live -= 1
        return {}

    jobs = [
        await queue.submit(kind="execution", tenant="noisy", key=f"p{i}", run=work)
        for i in range(6)
    ]
    await _drain(queue, jobs)
    assert peak <= 1, "a single tenant exceeded its per-tenant concurrency limit"


async def test_queue_rejects_rather_than_accepting_unbounded_work(state):
    """Backpressure: refuse with Retry-After instead of timing everyone out."""
    limits = QueueLimits(
        max_concurrent_global=1, max_concurrent_per_tenant=1,
        max_queued=3, max_queued_per_tenant=3,
    )
    queue = JobQueue(limits, state=state)
    release = asyncio.Event()

    async def work() -> dict:
        await release.wait()
        return {}

    accepted = []
    for index in range(3):
        accepted.append(
            await queue.submit(kind="execution", tenant="t", key=f"p{index}", run=work)
        )

    with pytest.raises(JobRejected) as excinfo:
        await queue.submit(kind="execution", tenant="t", key="overflow", run=work)
    assert excinfo.value.retry_after > 0

    release.set()
    await _drain(queue, accepted)


async def test_per_tenant_queue_limit_is_independent(state):
    limits = QueueLimits(
        max_concurrent_global=1, max_concurrent_per_tenant=1,
        max_queued=100, max_queued_per_tenant=2,
    )
    queue = JobQueue(limits, state=state)
    release = asyncio.Event()

    async def work() -> dict:
        await release.wait()
        return {}

    a1 = await queue.submit(kind="execution", tenant="a", key="p1", run=work)
    a2 = await queue.submit(kind="execution", tenant="a", key="p2", run=work)
    with pytest.raises(JobRejected):
        await queue.submit(kind="execution", tenant="a", key="p3", run=work)

    # A different tenant is unaffected by tenant A's backlog.
    b1 = await queue.submit(kind="execution", tenant="b", key="p4", run=work)

    release.set()
    await _drain(queue, [a1, a2, b1])


async def test_failing_job_is_recorded_not_swallowed(state):
    queue = JobQueue(QueueLimits(max_concurrent_global=2), state=state)

    async def boom() -> dict:
        raise ValueError("kaboom")

    job = await queue.submit(kind="execution", tenant="t", key="p", run=boom)
    await _drain(queue, [job])
    record = await queue.get(job.id)
    assert record.status is JobStatus.FAILED
    assert "kaboom" in record.error


async def test_job_timeout_is_enforced(state):
    queue = JobQueue(
        QueueLimits(max_concurrent_global=2, job_timeout_seconds=0.1), state=state
    )

    async def forever() -> dict:
        await asyncio.sleep(30)
        return {}

    job = await queue.submit(kind="execution", tenant="t", key="p", run=forever)
    await _drain(queue, [job], timeout=5)
    record = await queue.get(job.id)
    assert record.status is JobStatus.FAILED
    assert "budget" in record.error


async def test_drain_lets_in_flight_work_finish(state):
    queue = JobQueue(QueueLimits(max_concurrent_global=2), state=state)
    finished = asyncio.Event()

    async def work() -> dict:
        await asyncio.sleep(0.1)
        finished.set()
        return {}

    job = await queue.submit(kind="execution", tenant="t", key="p", run=work)
    await queue.drain(timeout=5)
    assert finished.is_set(), "drain cancelled a job that had time to finish"
    record = await queue.get(job.id)
    assert record.status is JobStatus.SUCCEEDED

    # Draining also closes admission.
    with pytest.raises(JobRejected):
        await queue.submit(kind="execution", tenant="t", key="p2", run=work)


async def _drain(queue: JobQueue, jobs, timeout: float = 15.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    ids = {job.id for job in jobs}
    while asyncio.get_running_loop().time() < deadline:
        records = [await queue.get(job_id) for job_id in ids]
        if all(
            record and record.status
            in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
            for record in records
        ):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("jobs did not finish within the timeout")


# ------------------------------------------------------------ rate limit ---
async def test_rate_limiter_allows_a_burst_then_refuses(state):
    limiter = RateLimiter({"heavy": Rate(capacity=3, per_seconds=60)}, state=state)
    for _ in range(3):
        assert (await limiter.check("tenant-a", "heavy")).allowed

    decision = await limiter.check("tenant-a", "heavy")
    assert not decision.allowed
    assert decision.retry_after >= 1
    assert decision.headers()["Retry-After"] == str(decision.retry_after)


async def test_rate_limits_are_per_tenant(state):
    limiter = RateLimiter({"heavy": Rate(capacity=1, per_seconds=60)}, state=state)
    assert (await limiter.check("tenant-a", "heavy")).allowed
    assert not (await limiter.check("tenant-a", "heavy")).allowed
    # One tenant exhausting its budget must not affect another.
    assert (await limiter.check("tenant-b", "heavy")).allowed


async def test_rate_limiter_refills_over_time(state):
    limiter = RateLimiter({"read": Rate(capacity=2, per_seconds=0.2)}, state=state)
    assert (await limiter.check("t", "read")).allowed
    assert (await limiter.check("t", "read")).allowed
    assert not (await limiter.check("t", "read")).allowed
    await asyncio.sleep(0.25)
    assert (await limiter.check("t", "read")).allowed


async def test_rate_limiter_can_be_disabled(state):
    limiter = RateLimiter({"read": Rate(capacity=1, per_seconds=60)}, state=state, enabled=False)
    for _ in range(50):
        assert (await limiter.check("t", "read")).allowed


# ---------------------------------------------------------------- state ----
async def test_lock_serialises_read_modify_write(state):
    """Without the lock this is a lost update; with it, every increment lands."""
    await state.set_json("counter", {"value": 0})

    async def increment() -> None:
        async with state.lock("counter", ttl=5, timeout=10):
            current = await state.get_json("counter")
            await asyncio.sleep(0)          # force interleaving
            await state.set_json("counter", {"value": current["value"] + 1})

    await asyncio.gather(*(increment() for _ in range(30)))
    assert (await state.get_json("counter"))["value"] == 30


async def test_lock_is_exclusive(state):
    holder = await state.acquire("k", ttl=5, timeout=1)
    assert holder is not None
    assert await state.acquire("k", ttl=5, timeout=0.05) is None
    await state.release("k", holder)
    assert await state.acquire("k", ttl=5, timeout=1) is not None


async def test_lock_release_requires_ownership(state):
    holder = await state.acquire("k", ttl=5, timeout=1)
    await state.release("k", "someone-elses-token")
    # Still held by the real owner.
    assert await state.acquire("k", ttl=5, timeout=0.05) is None
    await state.release("k", holder)


async def test_atomic_incr_under_concurrency(state):
    await asyncio.gather(*(state.incr("hits") for _ in range(100)))
    assert await state.get_int("hits") == 100


async def test_pubsub_delivers_to_subscribers(state):
    received: list[dict] = []

    async def consume() -> None:
        async for payload in state.subscribe("chan"):
            received.append(payload)
            if len(received) >= 2:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await state.publish("chan", {"n": 1})
    await state.publish("chan", {"n": 2})
    await asyncio.wait_for(task, timeout=5)
    assert [item["n"] for item in received] == [1, 2]


# ---------------------------------------------------- subprocess runner ----
async def test_run_process_falls_back_when_the_loop_cannot_spawn(tmp_path, monkeypatch):
    """A loop without subprocess support must not break sandboxed execution.

    uvicorn's Windows multi-worker mode hands workers a SelectorEventLoop, whose
    `create_subprocess_exec` raises NotImplementedError. Before the fallback,
    every test run failed with a bare NotImplementedError as soon as you scaled
    past one worker.
    """
    import sys

    from app.execution import process_manager
    from app.security.execution_security import scrub_env

    async def unsupported(*_args, **_kwargs):
        raise NotImplementedError

    monkeypatch.setattr(process_manager.asyncio, "create_subprocess_exec", unsupported)

    result = await process_manager.run_process(
        [sys.executable, "-c", "print('hello from the fallback')"],
        cwd=tmp_path,
        env=scrub_env(),
        timeout=60,
    )
    assert result.exit_code == 0, result.stderr
    assert "hello from the fallback" in result.stdout
    assert not result.timed_out


async def test_threaded_fallback_enforces_the_timeout(tmp_path, monkeypatch):
    import sys

    from app.execution import process_manager
    from app.security.execution_security import scrub_env

    async def unsupported(*_args, **_kwargs):
        raise NotImplementedError

    monkeypatch.setattr(process_manager.asyncio, "create_subprocess_exec", unsupported)

    result = await process_manager.run_process(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        env=scrub_env(),
        timeout=1.0,
    )
    assert result.timed_out, "a hung child must be killed, not awaited forever"
    assert result.duration_ms < 20_000


# ------------------------------------------------------------- identity ----
def test_parse_api_keys_derives_distinct_tenants():
    mapping = parse_api_keys("key-one:acme,key-two")
    assert mapping["key-one"] == "acme"
    assert mapping["key-two"].startswith("t_")
    assert len(set(mapping.values())) == 2


def test_open_mode_is_single_tenant():
    principal = resolve_principal(
        auth_mode="open", authorization=None, api_keys={}, admin_keys=set()
    )
    assert principal.tenant == "public"
    assert principal.is_anonymous


def test_apikey_mode_requires_a_token():
    with pytest.raises(AuthError, match="missing bearer token"):
        resolve_principal(
            auth_mode="apikey", authorization=None, api_keys={"k": "t"}, admin_keys=set()
        )


def test_apikey_mode_rejects_unknown_keys():
    with pytest.raises(AuthError, match="invalid API key"):
        resolve_principal(
            auth_mode="apikey",
            authorization="Bearer nope",
            api_keys={"k": "t"},
            admin_keys=set(),
        )


def test_apikey_mode_maps_key_to_tenant():
    principal = resolve_principal(
        auth_mode="apikey",
        authorization="Bearer secret-key",
        api_keys={"secret-key": "acme"},
        admin_keys={"secret-key"},
    )
    assert principal.tenant == "acme"
    assert principal.is_admin
    # The label must not contain the key itself.
    assert "secret-key" not in principal.label


def test_non_bearer_schemes_are_refused():
    with pytest.raises(AuthError):
        resolve_principal(
            auth_mode="apikey",
            authorization="Basic secret-key",
            api_keys={"secret-key": "acme"},
            admin_keys=set(),
        )
