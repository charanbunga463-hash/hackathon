"""Repair session orchestration + persistence.

Owns the long-running work: a repair runs as a background task so the HTTP
request returns immediately and the UI follows progress over SSE. Approval
decisions are routed back into the running orchestrator through its gate.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from ..agents.orchestrator import RepairOrchestrator
from ..ai.openai_client import get_openai_client
from ..config.settings import Settings
from ..execution.api_runner import run_api_probe
from ..execution.sandbox import Sandbox, build_sandbox
from ..execution.test_runner import run_tests
from ..models.events import AgentEvent, EventLevel, EventType
from ..models.execution import ExecutionRecord, RunMode, RunOptions
from ..models.report import (
    RepairSession,
    RepairSessionSummary,
    RepairStage,
    RepairVerdict,
)
from ..patches.snapshot_manager import SnapshotManager
from ..runtime.concurrency import io_bound
from ..runtime.jobs import JobQueue, JobRecord, get_job_queue
from ..runtime.metrics import get_metrics
from ..utils.filesystem import ensure_dir, read_json, write_json_atomic
from ..utils.logging import get_logger
from .event_service import EventBus, get_event_bus
from .project_service import ProjectError, ProjectService

logger = get_logger(__name__)


class RepairError(RuntimeError):
    pass


class RepairService:
    def __init__(
        self,
        settings: Settings,
        projects: ProjectService,
        bus: EventBus | None = None,
        queue: "JobQueue | None" = None,
    ) -> None:
        self.settings = settings
        self.projects = projects
        self.bus = bus or get_event_bus()
        self.queue = queue or get_job_queue()
        self._active: dict[str, RepairOrchestrator] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._sandbox: Sandbox | None = None
        self._sandbox_lock = asyncio.Lock()
        self._approval_listener: asyncio.Task | None = None
        self._records = self._build_record_store()

    @staticmethod
    def _build_record_store():
        """Postgres for sessions and executions, or None to use JSON files."""
        from ..db import database_enabled

        if database_enabled():
            from ..db.stores import PostgresRecordStore

            return PostgresRecordStore()
        return None

    def _owner_of(self, project_id: str) -> str:
        """The tenant a record belongs to, so rows carry their owner."""
        project = self.projects.store.load(project_id)
        return project.owner if project is not None else "public"

    # ---------------------------------------------------------- sandbox ---
    def sandbox_if_built(self) -> Sandbox | None:
        """The sandbox we have actually resolved, or None if nothing has run yet.

        Synchronous callers use this instead of guessing from configuration, so
        no surface can claim isolation that was never proven.
        """
        return self._sandbox

    async def sandbox(self) -> Sandbox:
        # Guarded: concurrent first-requests would otherwise each build a
        # sandbox, and in docker mode each build probes (and can build) the
        # image simultaneously.
        if self._sandbox is not None:
            return self._sandbox
        async with self._sandbox_lock:
            if self._sandbox is None:
                self._sandbox = await build_sandbox(self.settings)
                capabilities = self._sandbox.capabilities()
                if not capabilities.isolated:
                    logger.warning(
                        "LOCAL TRUSTED MODE active — project code runs without isolation"
                    )
            return self._sandbox

    # --------------------------------------------------------- execution --
    async def submit_execution(
        self,
        project_id: str,
        mode: RunMode,
        *,
        tenant: str,
        options: RunOptions | None = None,
    ) -> tuple[JobRecord, "asyncio.Future[ExecutionRecord]"]:
        """Queue an execution under admission control.

        Returns the job record immediately plus a future the caller may await
        with its own deadline, so a client that gives up waiting does not
        cancel work the queue already admitted.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ExecutionRecord] = loop.create_future()

        async def run() -> dict:
            try:
                record = await self.run_execution(project_id, mode, options=options)
            except Exception as exc:  # noqa: BLE001
                if not future.done():
                    future.set_exception(exc)
                raise
            if not future.done():
                future.set_result(record)
            return {
                "execution_id": record.id,
                "healthy": record.healthy,
                "failures": record.failure_count,
            }

        job = await self.queue.submit(
            kind="execution", tenant=tenant, key=project_id, run=run
        )
        return job, future

    async def run_execution(
        self, project_id: str, mode: RunMode, *, options: RunOptions | None = None
    ) -> ExecutionRecord:
        """TEST MODE or API MODE, recorded and broadcast.

        `options` carries the caller's saved preferences (probe timeout, whether
        write verbs are called). Absent, the deployment defaults apply.
        """
        options = options or RunOptions()
        project = await self.projects.ensure_analyzed_async(project_id)
        workspace = self.projects.workspace(project_id)
        sandbox = await self.sandbox()
        record_id = f"exec_{project_id[-6:]}_{mode.value}_{int(asyncio.get_event_loop().time() * 1000)}"

        await self.bus.publish(
            AgentEvent(
                type=EventType.EXECUTION_STARTED,
                message=f"Running {mode.value} mode in the {sandbox.kind} runner",
                project_id=project_id,
                data={"mode": mode.value, "runner": sandbox.kind},
            )
        )

        record = ExecutionRecord(
            id=record_id,
            project_id=project_id,
            mode=mode,
            runner=sandbox.kind,
            isolated=sandbox.capabilities().isolated,
        )

        if mode is RunMode.TEST:
            if not project.metadata or not project.metadata.test_files:
                await self.bus.publish(
                    AgentEvent(
                        type=EventType.WARNING,
                        level=EventLevel.WARNING,
                        message="This project has no test files; use API mode to detect failures.",
                        project_id=project_id,
                    )
                )
            result = await run_tests(sandbox, workspace)
            record.test_result = result
            record.failure_count = len(result.failures)
            record.healthy = result.all_passed
            record.label = result.summary_line()
        else:
            result = await run_api_probe(
                sandbox,
                workspace,
                project.metadata,
                include_write_methods=options.include_write_methods,
                probe_timeout_seconds=options.probe_timeout_seconds,
            )
            record.api_result = result
            record.failure_count = len(result.failures)
            record.healthy = result.all_ok
            record.label = (
                f"{len(result.probes)} endpoint(s) probed, {record.failure_count} failing"
                if result.started
                else f"the API did not start: {(result.startup_error or '')[:160]}"
            )

        await io_bound(self._save_execution, project_id, record)
        await self.projects.record_run(
            project_id, failures=record.failure_count, verdict=None
        )

        await self.bus.publish(
            AgentEvent(
                type=EventType.EXECUTION_FINISHED,
                level=EventLevel.SUCCESS if record.healthy else EventLevel.WARNING,
                message=record.label,
                project_id=project_id,
                data={
                    "mode": mode.value,
                    "healthy": record.healthy,
                    "failures": record.failure_count,
                    "execution_id": record.id,
                },
            )
        )
        for failure in record.failures():
            await self.bus.publish(
                AgentEvent(
                    type=EventType.FAILURE_DETECTED,
                    level=EventLevel.ERROR,
                    message=failure.headline(),
                    project_id=project_id,
                    data={
                        "failure_id": failure.id,
                        "error_type": failure.error_type,
                        "file": failure.file,
                        "line": failure.line,
                        "test": failure.test,
                        "endpoint": failure.endpoint,
                        "status_code": failure.status_code,
                        "severity": failure.severity.value,
                    },
                )
            )
        return record

    def _executions_dir(self, project_id: str) -> Path:
        return ensure_dir(self.projects.project_dir(project_id) / "executions")

    def _save_execution(self, project_id: str, record: ExecutionRecord) -> None:
        if self._records is not None:
            self._records.save_execution(project_id, self._owner_of(project_id), record)
            return
        write_json_atomic(
            self._executions_dir(project_id) / f"{record.id}.json",
            record.model_dump(mode="json"),
        )

    def list_executions(self, project_id: str, limit: int = 20) -> list[ExecutionRecord]:
        if self._records is not None:
            return self._records.list_executions(project_id, limit)
        directory = self._executions_dir(project_id)
        records: list[ExecutionRecord] = []
        for path in sorted(directory.glob("*.json"), reverse=True)[:limit]:
            payload = read_json(path)
            if payload:
                try:
                    records.append(ExecutionRecord.model_validate(payload))
                except Exception:  # noqa: BLE001
                    continue
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def latest_execution(self, project_id: str) -> ExecutionRecord | None:
        records = self.list_executions(project_id, limit=1)
        return records[0] if records else None

    # ------------------------------------------------------------ repair --
    async def start_repair(
        self,
        project_id: str,
        *,
        mode: RunMode = RunMode.TEST,
        failure_id: str | None = None,
        auto_approve: bool | None = None,
        tenant: str = "public",
        wait_for_session: float = 10.0,
        use_ai: bool = True,
    ) -> tuple[JobRecord, RepairSession | None]:
        """Queue a repair. Returns the job, plus the session once it has started.

        The queue owns execution, so a repair that cannot start yet waits for a
        slot instead of being refused or run anyway. The caller gets a session
        as soon as one exists; if the job is still queued it gets `None` and
        should poll the job id.
        """
        if self.is_running(project_id):
            raise RepairError("a repair is already running for this project")

        started: asyncio.Event = asyncio.Event()
        # Held for the caller below: `_active` is dropped as soon as the repair
        # ends, and a fast repair can finish before the caller looks.
        holder: dict[str, RepairOrchestrator] = {}

        async def run() -> dict:
            project = await self.projects.ensure_analyzed_async(project_id)
            sandbox = await self.sandbox()
            orchestrator = RepairOrchestrator(
                settings=self.settings,
                workspace=self.projects.workspace(project_id),
                metadata=project.metadata,
                sandbox=sandbox,
                snapshots=SnapshotManager(
                    self.projects.workspace(project_id),
                    self.projects.snapshots_dir(project_id),
                    project_id,
                ),
                project_id=project_id,
                project_name=project.name,
                # `use_ai=False` is the caller's "AI analysis: off" preference.
                # Passing no client is what makes the orchestrator report
                # `deterministic-offline` as its engine, so the run is labelled
                # honestly rather than silently skipping a stage.
                ai_client=get_openai_client(self.settings) if use_ai else None,
                emit=self.bus.publish,
            )
            self._active[project_id] = orchestrator
            holder["orchestrator"] = orchestrator
            task = asyncio.current_task()
            if task is not None:
                self._tasks[project_id] = task

            # Let the caller observe the session as soon as it exists.
            async def signal_when_ready() -> None:
                for _ in range(500):
                    if orchestrator.session is not None:
                        started.set()
                        return
                    await asyncio.sleep(0.02)
                started.set()

            watcher = asyncio.create_task(signal_when_ready())
            mirror = asyncio.create_task(self._mirror_active(project_id, orchestrator))
            try:
                session = await self._run_and_persist(
                    orchestrator, project_id, mode, failure_id, auto_approve
                )
            finally:
                watcher.cancel()
                mirror.cancel()
                # The session is on disk by now, so every worker reads it from
                # there. Keeping the finished orchestrator would pin *this*
                # process to one session forever, which is how two processes
                # end up answering the same question differently.
                self._active.pop(project_id, None)
                self._tasks.pop(project_id, None)
                with contextlib.suppress(Exception):
                    await self._clear_active_mirror(project_id)
                started.set()
            return {
                "session_id": session.id if session else None,
                "verdict": session.verdict.value if session else None,
                "verified": bool(session and session.verified),
            }

        job = await self.queue.submit(
            kind="repair", tenant=tenant, key=project_id, run=run
        )

        # Wait briefly for the session; a queued job legitimately has none yet.
        try:
            await asyncio.wait_for(started.wait(), timeout=wait_for_session)
        except asyncio.TimeoutError:
            return job, None
        orchestrator = holder.get("orchestrator") or self._active.get(project_id)
        return job, (orchestrator.session if orchestrator else None)

    async def _run_and_persist(
        self,
        orchestrator: RepairOrchestrator,
        project_id: str,
        mode: RunMode,
        failure_id: str | None,
        auto_approve: bool | None,
    ) -> RepairSession:
        try:
            session = await orchestrator.run(
                mode=mode, target_failure_id=failure_id, auto_approve=auto_approve
            )
        except asyncio.CancelledError:
            logger.info("repair for %s cancelled", project_id)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("repair task crashed")
            session = orchestrator.session
            if session is not None:
                session.verdict = RepairVerdict.ERROR
                session.error = f"{type(exc).__name__}: {exc}"
        if session is not None:
            await io_bound(self.save_session, project_id, session)
            await self.projects.record_run(
                project_id,
                failures=0,
                verdict=session.verdict.value,
                attempted=session.verdict
                not in {RepairVerdict.NO_FAILURE_DETECTED, RepairVerdict.PENDING},
                verified=session.verified,
            )
            get_metrics().repairs.inc(verdict=session.verdict.value)
            await self.bus.publish(
                AgentEvent(
                    type=EventType.SESSION_FINISHED,
                    level=EventLevel.SUCCESS if session.verified else EventLevel.WARNING,
                    message=session.summary or session.verdict.value,
                    project_id=project_id,
                    session_id=session.id,
                    data={
                        "verdict": session.verdict.value,
                        "verified": session.verified,
                        "attempts": len(session.attempts),
                        "duration_ms": session.duration_ms,
                    },
                )
            )
        return session

    # -------------------------------------------------- approval routing ---
    APPROVAL_CHANNEL = "approvals"

    async def start_approval_listener(self) -> None:
        """Route approvals that land on a different worker than the repair.

        With multiple workers, the developer's POST is load-balanced anywhere.
        If it lands on a worker that is not running the orchestrator, applying
        the patch locally is impossible — so decisions are published and each
        worker resolves the gate for sessions it actually owns.
        """
        from ..runtime.state import MemoryStateBackend, get_state_backend

        state = get_state_backend()
        if isinstance(state, MemoryStateBackend):
            return  # single worker: decide() already reaches the orchestrator
        if self._approval_listener is not None:
            return

        async def listen() -> None:
            while True:
                try:
                    async for payload in state.subscribe(self.APPROVAL_CHANNEL):
                        self._apply_decision_locally(
                            payload.get("project_id", ""),
                            payload.get("patch_id", ""),
                            bool(payload.get("approve")),
                            payload.get("note"),
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("approval listener dropped (%s); reconnecting", exc)
                    await asyncio.sleep(1.0)

        self._approval_listener = asyncio.create_task(listen(), name="approval-listener")

    async def stop_approval_listener(self) -> None:
        if self._approval_listener is not None:
            self._approval_listener.cancel()
            try:
                await self._approval_listener
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._approval_listener = None

    def _apply_decision_locally(
        self, project_id: str, patch_id: str, approve: bool, note: str | None
    ) -> bool:
        orchestrator = self._active.get(project_id)
        if orchestrator is None or orchestrator.session is None:
            return False
        if orchestrator.session.pending_patch_id != patch_id:
            return False
        orchestrator.approval.decide(approve, note)
        return True

    async def decide(
        self, project_id: str, patch_id: str, approve: bool, note: str | None = None
    ) -> bool:
        # Fast path: the repair is running on this worker.
        if self._apply_decision_locally(project_id, patch_id, approve, note):
            return True

        # Otherwise it may be on a sibling worker. Publish and let it resolve.
        from ..runtime.state import MemoryStateBackend, get_state_backend

        state = get_state_backend()
        if not isinstance(state, MemoryStateBackend):
            await state.publish(
                self.APPROVAL_CHANNEL,
                {
                    "project_id": project_id,
                    "patch_id": patch_id,
                    "approve": approve,
                    "note": note,
                },
            )
            return True

        orchestrator = self._active.get(project_id)
        if orchestrator is None or orchestrator.session is None:
            raise RepairError("no repair is currently awaiting approval for this project")
        raise RepairError(
            f"patch {patch_id} is not the patch awaiting approval "
            f"(current: {orchestrator.session.pending_patch_id})"
        )

    async def cancel(self, project_id: str) -> bool:
        task = self._tasks.get(project_id)
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        # A cancelled task skips its own cleanup, so drop the mirror here too;
        # otherwise siblings keep reporting "running" until the TTL lapses.
        await self._clear_active_mirror(project_id)
        return True

    def active_session(self, project_id: str) -> RepairSession | None:
        orchestrator = self._active.get(project_id)
        return orchestrator.session if orchestrator else None

    def is_running(self, project_id: str) -> bool:
        task = self._tasks.get(project_id)
        return task is not None and not task.done()

    # ---------------------------------------------- cross-worker session ---
    # `_active` is per-process. A poll that lands on any other worker sees no
    # live session, and falling back to the newest session on disk answers with
    # a *different*, already-finished run — so the UI flips between the live
    # repair and a stale verdict from one request to the next. The owner
    # mirrors the in-flight session into shared state; everyone else reads it.
    ACTIVE_KEY_PREFIX = "repair:active:"
    ACTIVE_MIRROR_SECONDS = 1.5
    # Comfortably longer than the refresh, so a slow tick never blanks the
    # session — but short enough that a worker dying mid-repair stops the UI
    # from claiming "running" forever.
    ACTIVE_TTL_SECONDS = 12.0

    def _active_key(self, project_id: str) -> str:
        return f"{self.ACTIVE_KEY_PREFIX}{project_id}"

    async def _mirror_active(self, project_id: str, orchestrator: RepairOrchestrator) -> None:
        """Republish the in-flight session until the repair ends."""
        from ..runtime.state import get_state_backend

        state = get_state_backend()
        key = self._active_key(project_id)
        while True:
            session = orchestrator.session
            if session is None:
                # The session is built a moment after the task starts. Publish
                # it the instant it exists — waiting for the next tick leaves a
                # window where siblings answer "no repair session yet".
                await asyncio.sleep(0.02)
                continue
            try:
                await state.set_json(
                    key,
                    {"running": True, "session": session.model_dump(mode="json")},
                    ttl=self.ACTIVE_TTL_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001 - never break the repair
                logger.warning("could not mirror the active session: %s", exc)
            await asyncio.sleep(self.ACTIVE_MIRROR_SECONDS)

    async def _clear_active_mirror(self, project_id: str) -> None:
        from ..runtime.state import get_state_backend

        try:
            await get_state_backend().delete(self._active_key(project_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not clear the active-session mirror: %s", exc)

    async def _mirrored_active(self, project_id: str) -> tuple[bool, RepairSession] | None:
        from ..runtime.state import get_state_backend

        try:
            payload = await get_state_backend().get_json(self._active_key(project_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("shared state unreadable: %s", exc)
            return None
        if not isinstance(payload, dict) or not payload.get("session"):
            return None
        try:
            session = RepairSession.model_validate(payload["session"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("unreadable mirrored session for %s: %s", project_id, exc)
            return None
        return bool(payload.get("running")), session

    async def active_snapshot(
        self, project_id: str, tenant: str | None = None
    ) -> tuple[bool, RepairSession | None]:
        """What to show for this project, whichever worker is asked.

        Resolution order matters: a live session always wins over the newest
        record on disk, because during a repair that record is the *previous*
        run and showing it would contradict what the owning worker reports.
        """
        session = self.active_session(project_id)
        if session is not None:
            return self.is_running(project_id), session
        mirrored = await self._mirrored_active(project_id)
        if mirrored is not None:
            return mirrored
        sessions = await self.list_sessions_async(project_id, limit=1, tenant=tenant)
        return False, (sessions[0] if sessions else None)

    # ----------------------------------------------------- session store --
    def save_session(self, project_id: str, session: RepairSession) -> None:
        if self._records is not None:
            self._records.save_session(project_id, self._owner_of(project_id), session)
            return
        directory = ensure_dir(self.projects.sessions_dir(project_id))
        write_json_atomic(directory / f"{session.id}.json", session.model_dump(mode="json"))

    def load_session(self, project_id: str, session_id: str) -> RepairSession | None:
        active = self.active_session(project_id)
        if active is not None and active.id == session_id:
            return active
        if self._records is not None:
            return self._records.load_session(project_id, session_id)
        payload = read_json(self.projects.sessions_dir(project_id) / f"{session_id}.json")
        if payload is None:
            return None
        try:
            return RepairSession.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("unreadable session %s: %s", session_id, exc)
            return None

    def list_sessions(
        self,
        project_id: str | None = None,
        limit: int = 100,
        tenant: str | None = None,
    ) -> list[RepairSession]:
        sessions: list[RepairSession] = []
        if self._records is not None:
            # One indexed query, rather than walking every project directory
            # this tenant owns and parsing every file in it.
            sessions = self._records.list_sessions(project_id, tenant, limit)
            for pid in [project_id] if project_id else []:
                active = self.active_session(pid)
                if active is not None and not any(s.id == active.id for s in sessions):
                    sessions.append(active)
            return sorted(sessions, key=lambda s: s.created_at, reverse=True)[:limit]

        project_ids = (
            [project_id]
            if project_id
            else [summary.id for summary in self.projects.list_projects(tenant)]
        )
        for pid in project_ids:
            directory = self.projects.sessions_dir(pid)
            if not directory.exists():
                continue
            for path in directory.glob("*.json"):
                payload = read_json(path)
                if not payload:
                    continue
                try:
                    sessions.append(RepairSession.model_validate(payload))
                except Exception:  # noqa: BLE001
                    continue
            active = self.active_session(pid)
            if active is not None and not any(s.id == active.id for s in sessions):
                sessions.append(active)
        return sorted(sessions, key=lambda s: s.created_at, reverse=True)[:limit]

    def list_session_summaries(
        self, project_id: str | None = None, limit: int = 100, tenant: str | None = None
    ) -> list[RepairSessionSummary]:
        return [
            RepairSessionSummary.from_session(session)
            for session in self.list_sessions(project_id, limit, tenant)
        ]

    def find_session(
        self, session_id: str, tenant: str | None = None
    ) -> tuple[str, RepairSession] | None:
        """Locate a session, scoped to the tenant's own projects."""
        if self._records is not None:
            # Indexed lookup by id, with the owner in the WHERE clause so a
            # guessed session id from another account simply does not match.
            return self._records.find_session(session_id, tenant)
        for summary in self.projects.list_projects(tenant):
            session = self.load_session(summary.id, session_id)
            if session is not None:
                return summary.id, session
        return None

    async def find_session_async(
        self, session_id: str, tenant: str | None = None
    ) -> tuple[str, RepairSession] | None:
        return await io_bound(self.find_session, session_id, tenant)

    async def list_sessions_async(
        self, project_id: str | None = None, limit: int = 100, tenant: str | None = None
    ) -> list[RepairSession]:
        return await io_bound(self.list_sessions, project_id, limit, tenant)

    async def list_session_summaries_async(
        self, project_id: str | None = None, limit: int = 100, tenant: str | None = None
    ) -> list[RepairSessionSummary]:
        return await io_bound(self.list_session_summaries, project_id, limit, tenant)

    async def load_session_async(self, project_id: str, session_id: str) -> RepairSession | None:
        session = await io_bound(self.load_session, project_id, session_id)
        if session is not None:
            return session
        # An in-flight session owned by another worker is not on disk yet.
        mirrored = await self._mirrored_active(project_id)
        if mirrored is not None and mirrored[1].id == session_id:
            return mirrored[1]
        return None

    async def list_executions_async(
        self, project_id: str, limit: int = 20
    ) -> list[ExecutionRecord]:
        return await io_bound(self.list_executions, project_id, limit)

    async def latest_execution_async(self, project_id: str) -> ExecutionRecord | None:
        return await io_bound(self.latest_execution, project_id)

    # ------------------------------------------------------- maintenance --
    def rollback_session(self, project_id: str, session_id: str) -> dict:
        """Undo the applied patch of a completed session."""
        session = self.load_session(project_id, session_id)
        if session is None:
            raise RepairError(f"session {session_id} not found")
        applied = None
        for attempt in reversed(session.attempts):
            if attempt.applied is not None and not attempt.applied.rolled_back:
                applied = attempt.applied
                break
        if applied is None:
            raise RepairError("this session has no applied patch to roll back")

        from ..patches.rollback_manager import RollbackError, rollback_patch

        snapshots = SnapshotManager(
            self.projects.workspace(project_id),
            self.projects.snapshots_dir(project_id),
            project_id,
        )
        try:
            rollback_patch(
                self.projects.workspace(project_id), applied, snapshots,
                reason="manual rollback requested by the developer",
            )
        except RollbackError as exc:
            raise RepairError(str(exc)) from exc

        session.verdict = RepairVerdict.ABORTED
        session.stage = RepairStage.DONE
        session.summary = (
            f"{session.summary} (Patch was manually rolled back.)".strip()
        )
        self.save_session(project_id, session)
        return {
            "rolled_back": True,
            "files": applied.files_changed,
            "snapshot_id": applied.snapshot_id,
        }


_service: RepairService | None = None


def get_repair_service(settings: Settings, projects: ProjectService) -> RepairService:
    global _service
    if _service is None:
        _service = RepairService(settings, projects)
    return _service


def reset_repair_service() -> None:
    """Test hook: drop the singleton so a fresh settings object takes effect."""
    global _service
    _service = None
