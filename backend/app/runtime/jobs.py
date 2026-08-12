"""Bounded job execution with admission control.

A repair is not a web request. It starts containers and runs a real test suite:
seconds to minutes of CPU, hundreds of MB of RAM. Serving 1000 concurrent users
does *not* mean running 1000 concurrent repairs — it means accepting 1000 users
and running as many repairs as the hardware can actually finish, with everyone
else queued and told where they stand.

Three limits, in order:

  1. **Per-tenant concurrency** — one noisy user cannot monopolise the pool.
  2. **Global concurrency** — the box runs N heavy jobs, no more, ever.
  3. **Queue depth** — beyond this we reject with 429 + Retry-After rather than
     accepting work we cannot finish. Admitting unbounded work is how systems
     die: every request times out instead of most succeeding.

Job records live in the shared state backend, so a client polling any worker
sees the true status of a job running on another.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable

from ..utils.logging import get_logger
from ..utils.timestamps import utcnow_iso
from .state import StateBackend, get_state_backend

logger = get_logger(__name__)

JOB_TTL_SECONDS = 3600.0


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class JobRejected(RuntimeError):
    """Admission control refused the job. Carries a Retry-After hint."""

    def __init__(self, message: str, *, retry_after: int = 30) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class JobConflict(RuntimeError):
    """An equivalent job is already in flight for this key."""


@dataclass
class JobRecord:
    id: str
    kind: str
    tenant: str
    key: str
    status: JobStatus = JobStatus.QUEUED
    created_at: str = field(default_factory=utcnow_iso)
    started_at: str | None = None
    finished_at: str | None = None
    queue_position: int = 0
    error: str | None = None
    result: dict | None = None
    worker: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "tenant": self.tenant,
            "key": self.key,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "queue_position": self.queue_position,
            "error": self.error,
            "result": self.result,
            "worker": self.worker,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "JobRecord":
        return cls(
            id=payload["id"],
            kind=payload.get("kind", ""),
            tenant=payload.get("tenant", ""),
            key=payload.get("key", ""),
            status=JobStatus(payload.get("status", "queued")),
            created_at=payload.get("created_at", utcnow_iso()),
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
            queue_position=payload.get("queue_position", 0),
            error=payload.get("error"),
            result=payload.get("result"),
            worker=payload.get("worker", ""),
        )


@dataclass
class QueueLimits:
    max_concurrent_global: int = 4
    max_concurrent_per_tenant: int = 1
    max_queued: int = 200
    max_queued_per_tenant: int = 5
    job_timeout_seconds: float = 1800.0


class JobQueue:
    """Admission control + a bounded worker pool for heavy jobs."""

    def __init__(
        self,
        limits: QueueLimits,
        *,
        state: StateBackend | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.limits = limits
        self.state = state or get_state_backend()
        self.worker_id = worker_id or f"w-{uuid.uuid4().hex[:8]}"
        self._global = asyncio.Semaphore(limits.max_concurrent_global)
        self._tenant_slots: dict[str, asyncio.Semaphore] = {}
        self._queued = 0
        self._queued_by_tenant: dict[str, int] = {}
        self._running: dict[str, asyncio.Task] = {}
        self._guard = asyncio.Lock()
        self._draining = False

    # ------------------------------------------------------------ helpers --
    def _tenant_semaphore(self, tenant: str) -> asyncio.Semaphore:
        semaphore = self._tenant_slots.get(tenant)
        if semaphore is None:
            semaphore = asyncio.Semaphore(self.limits.max_concurrent_per_tenant)
            self._tenant_slots[tenant] = semaphore
        return semaphore

    def _job_key(self, job_id: str) -> str:
        return f"job:{job_id}"

    async def _save(self, record: JobRecord) -> None:
        await self.state.set_json(self._job_key(record.id), record.as_dict(), ttl=JOB_TTL_SECONDS)

    async def get(self, job_id: str) -> JobRecord | None:
        payload = await self.state.get_json(self._job_key(job_id))
        return JobRecord.from_dict(payload) if payload else None

    # ------------------------------------------------------------- submit --
    async def submit(
        self,
        *,
        kind: str,
        tenant: str,
        key: str,
        run: Callable[[], Awaitable[dict | None]],
        dedupe: bool = True,
    ) -> JobRecord:
        """Admit a job or refuse it. Never blocks the caller on execution."""
        if self._draining:
            raise JobRejected("the server is shutting down and is not accepting new work", retry_after=30)

        async with self._guard:
            if dedupe and any(
                not task.done() for jid, task in self._running.items() if jid.startswith(f"{kind}:{key}:")
            ):
                raise JobConflict(f"a {kind} job is already running for {key}")

            tenant_queued = self._queued_by_tenant.get(tenant, 0)
            if tenant_queued >= self.limits.max_queued_per_tenant:
                raise JobRejected(
                    f"you already have {tenant_queued} job(s) waiting; "
                    "wait for one to finish before submitting more",
                    retry_after=15,
                )
            if self._queued >= self.limits.max_queued:
                raise JobRejected(
                    f"the server is at capacity ({self._queued} jobs queued). "
                    "Please retry shortly.",
                    retry_after=60,
                )
            self._queued += 1
            self._queued_by_tenant[tenant] = tenant_queued + 1
            position = self._queued

        record = JobRecord(
            id=f"{kind}:{key}:{uuid.uuid4().hex[:10]}",
            kind=kind,
            tenant=tenant,
            key=key,
            queue_position=position,
            worker=self.worker_id,
        )
        await self._save(record)
        await self.state.incr("metrics:jobs:submitted", 1)

        task = asyncio.create_task(self._run(record, run), name=record.id)
        self._running[record.id] = task
        task.add_done_callback(lambda t: self._running.pop(record.id, None))
        return record

    # ---------------------------------------------------------------- run --
    async def _run(self, record: JobRecord, run: Callable[[], Awaitable[dict | None]]) -> None:
        # A repair runs long after its request returned, and everything it
        # emits has to stay attributable to the tenant that asked for it —
        # otherwise the event bus cannot keep one user's activity off another
        # user's stream.
        from .middleware import tenant_var

        tenant_token = tenant_var.set(record.tenant)
        try:
            await self._run_inner(record, run)
        finally:
            tenant_var.reset(tenant_token)

    async def _run_inner(
        self, record: JobRecord, run: Callable[[], Awaitable[dict | None]]
    ) -> None:
        tenant_semaphore = self._tenant_semaphore(record.tenant)
        acquired_tenant = False
        acquired_global = False
        try:
            await tenant_semaphore.acquire()
            acquired_tenant = True
            await self._global.acquire()
            acquired_global = True

            async with self._guard:
                self._queued = max(0, self._queued - 1)
                remaining = self._queued_by_tenant.get(record.tenant, 1) - 1
                if remaining <= 0:
                    self._queued_by_tenant.pop(record.tenant, None)
                else:
                    self._queued_by_tenant[record.tenant] = remaining

            record.status = JobStatus.RUNNING
            record.started_at = utcnow_iso()
            record.queue_position = 0
            await self._save(record)
            await self.state.incr("metrics:jobs:running", 1)

            started = time.monotonic()
            try:
                result = await asyncio.wait_for(run(), timeout=self.limits.job_timeout_seconds)
                record.status = JobStatus.SUCCEEDED
                record.result = result if isinstance(result, dict) else None
                await self.state.incr("metrics:jobs:succeeded", 1)
            except asyncio.TimeoutError:
                record.status = JobStatus.FAILED
                record.error = (
                    f"job exceeded its {self.limits.job_timeout_seconds:g}s budget and was stopped"
                )
                await self.state.incr("metrics:jobs:timeout", 1)
            except asyncio.CancelledError:
                record.status = JobStatus.CANCELLED
                record.error = "cancelled"
                await self.state.incr("metrics:jobs:cancelled", 1)
                raise
            except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
                logger.exception("job %s failed", record.id)
                record.status = JobStatus.FAILED
                record.error = f"{type(exc).__name__}: {exc}"
                await self.state.incr("metrics:jobs:failed", 1)
            finally:
                await self.state.incr("metrics:jobs:running", -1)
                logger.info(
                    "job %s finished as %s in %.1fs",
                    record.id, record.status.value, time.monotonic() - started,
                )
        except asyncio.CancelledError:
            record.status = JobStatus.CANCELLED
            raise
        finally:
            if not acquired_global and not acquired_tenant:
                # Never made it out of the waiting room; undo the reservation.
                async with self._guard:
                    self._queued = max(0, self._queued - 1)
                    remaining = self._queued_by_tenant.get(record.tenant, 1) - 1
                    if remaining <= 0:
                        self._queued_by_tenant.pop(record.tenant, None)
                    else:
                        self._queued_by_tenant[record.tenant] = remaining
            if acquired_global:
                self._global.release()
            if acquired_tenant:
                tenant_semaphore.release()
            record.finished_at = utcnow_iso()
            await self._save(record)

    # ------------------------------------------------------------ control --
    async def cancel(self, job_id: str) -> bool:
        task = self._running.get(job_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def cancel_by_key(self, kind: str, key: str) -> int:
        cancelled = 0
        for job_id, task in list(self._running.items()):
            if job_id.startswith(f"{kind}:{key}:") and not task.done():
                task.cancel()
                cancelled += 1
        return cancelled

    def is_busy(self, kind: str, key: str) -> bool:
        return any(
            not task.done()
            for job_id, task in self._running.items()
            if job_id.startswith(f"{kind}:{key}:")
        )

    async def drain(self, timeout: float = 30.0) -> None:
        """Stop admitting work and let in-flight jobs finish."""
        self._draining = True
        tasks = [task for task in self._running.values() if not task.done()]
        if not tasks:
            return
        logger.info("draining %d in-flight job(s)", len(tasks))
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        for task in pending:
            task.cancel()
        if pending:
            logger.warning("cancelled %d job(s) that did not drain in time", len(pending))

    def stats(self) -> dict:
        return {
            "worker": self.worker_id,
            "draining": self._draining,
            "queued": self._queued,
            "running": sum(1 for t in self._running.values() if not t.done()),
            "capacity": {
                "max_concurrent_global": self.limits.max_concurrent_global,
                "max_concurrent_per_tenant": self.limits.max_concurrent_per_tenant,
                "max_queued": self.limits.max_queued,
                "max_queued_per_tenant": self.limits.max_queued_per_tenant,
            },
            "tenants_waiting": len(self._queued_by_tenant),
        }


_queue: JobQueue | None = None


def init_job_queue(limits: QueueLimits, *, state: StateBackend | None = None) -> JobQueue:
    global _queue
    _queue = JobQueue(limits, state=state)
    return _queue


def get_job_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue(QueueLimits())
    return _queue


def reset_job_queue() -> None:
    global _queue
    _queue = None
