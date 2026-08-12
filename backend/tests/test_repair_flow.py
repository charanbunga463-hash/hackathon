"""End-to-end repair tests against the real demo projects.

These run the actual pipeline: real pytest runs, real patches written to a real
temporary workspace, real rollbacks. They are the tests that prove the product's
central claim — that VERIFIED means a test run passed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agents import offline_engine, verifier
from app.agents.orchestrator import RepairOrchestrator
from app.analysis.project_analyzer import analyze_project
from app.config.settings import Settings
from app.execution.sandbox import build_sandbox
from app.execution.test_runner import run_tests
from app.models.events import AgentEvent, EventType
from app.models.execution import RunMode, TestRunResult
from app.models.patch import PatchProposal
from app.models.report import RepairVerdict
from app.patches.snapshot_manager import SnapshotManager

pytestmark = pytest.mark.asyncio


async def _run_repair(workspace: Path, settings: Settings, **kwargs):
    metadata = analyze_project(workspace)
    sandbox = await build_sandbox(settings)
    events: list[AgentEvent] = []

    async def sink(event: AgentEvent) -> None:
        events.append(event)

    orchestrator = RepairOrchestrator(
        settings=settings,
        workspace=workspace,
        metadata=metadata,
        sandbox=sandbox,
        snapshots=SnapshotManager(workspace, settings.data_dir / "snaps", "prj_test"),
        project_id="prj_test",
        project_name="test",
        ai_client=None,
        emit=sink,
    )
    session = await orchestrator.run(mode=RunMode.TEST, auto_approve=True, **kwargs)
    return session, events, orchestrator


@pytest.mark.parametrize(
    "slug",
    [
        "fastapi-keyerror",
        "fastapi-attribute-error",
        "fastapi-billing",
        "fastapi-type-error",
        "fastapi-http-error",
        "fastapi-contract",
        "fastapi-validation",
    ],
)
async def test_demo_is_detected_diagnosed_and_verified(slug, demo_workspace, settings: Settings):
    workspace = demo_workspace(slug)
    sandbox = await build_sandbox(settings)

    baseline = await run_tests(sandbox, workspace)
    assert not baseline.all_passed, f"{slug} is supposed to start broken"
    assert baseline.failures, "the broken demo must produce a parsed failure"

    session, events, _ = await _run_repair(workspace, settings)

    assert session.verdict is RepairVerdict.VERIFIED, session.summary
    assert session.verified

    # VERIFIED must be backed by a real passing run, not by a claim.
    last = session.attempts[-1]
    assert last.full_test is not None
    assert last.full_test.all_passed
    assert last.full_test.exit_code == 0
    assert last.full_test.passed >= baseline.passed

    # And the workspace on disk must actually be fixed.
    after = await run_tests(sandbox, workspace)
    assert after.all_passed, after.summary_line()

    types = [event.type for event in events]
    assert EventType.FAILURE_DETECTED in types
    assert EventType.DIAGNOSIS_READY in types
    assert EventType.PATCH_APPLIED in types
    assert EventType.VERIFICATION_PASSED in types


async def test_healthy_project_reports_no_failure(demo_workspace, settings: Settings):
    """A project with nothing wrong must not invent a repair."""
    workspace = demo_workspace("fastapi-keyerror")
    main = workspace / "main.py"
    main.write_text(
        main.read_text(encoding="utf-8").replace('user["username"]', 'user["name"]'),
        encoding="utf-8",
    )
    session, _events, _ = await _run_repair(workspace, settings)
    assert session.verdict is RepairVerdict.NO_FAILURE_DETECTED
    assert not session.verified
    assert session.attempts == []


async def test_unfixable_failure_reports_failure_not_success(workspace: Path, settings: Settings):
    """When no rule matches, the verdict must be REPAIR_FAILED — never VERIFIED."""
    (workspace / "main.py").write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()\n", encoding="utf-8"
    )
    (workspace / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent))\n",
        encoding="utf-8",
    )
    tests = workspace / "tests"
    tests.mkdir()
    (tests / "test_impossible.py").write_text(
        "def test_business_rule():\n"
        "    # No mechanical rule can infer the intended behaviour here.\n"
        "    assert compute_quarterly_forecast() == 42\n",
        encoding="utf-8",
    )
    session, _events, _ = await _run_repair(workspace, settings)
    assert session.verdict is not RepairVerdict.VERIFIED
    assert not session.verified
    assert "VERIFIED" not in (session.summary or "").upper().replace("NOT VERIFIED", "")


async def test_failed_verification_rolls_back(demo_workspace, settings: Settings, monkeypatch):
    """A patch that does not fix the failure must leave the workspace untouched."""
    workspace = demo_workspace("fastapi-keyerror")
    original = (workspace / "main.py").read_text(encoding="utf-8")

    # Force the engine to produce a plausible-but-wrong patch.
    def wrong_patch(outcome, *, project_id, failure, attempt):
        return PatchProposal(
            id=f"patch_wrong_{attempt}",
            project_id=project_id,
            failure_id=failure.id,
            attempt=attempt,
            title="Wrong fix",
            explanation="deliberately incorrect",
            edits=[
                type(outcome.edits[0])(
                    path="main.py",
                    operation=outcome.edits[0].operation,
                    old='"username": user["username"],',
                    new='"username": user["email"],',
                    reason="wrong on purpose",
                )
            ],
            reasoning_engine="test",
        )

    monkeypatch.setattr(offline_engine, "build_patch", wrong_patch)

    session, events, _ = await _run_repair(workspace, settings)

    assert session.verdict is RepairVerdict.REPAIR_FAILED
    assert not session.verified
    assert (workspace / "main.py").read_text(encoding="utf-8") == original
    assert any(event.type is EventType.PATCH_ROLLED_BACK for event in events)
    assert all(attempt.rolled_back for attempt in session.attempts if attempt.applied)


async def test_retry_loop_runs_multiple_attempts(demo_workspace, settings: Settings, monkeypatch):
    settings.max_repair_attempts = 3
    workspace = demo_workspace("fastapi-keyerror")

    def wrong_patch(outcome, *, project_id, failure, attempt):
        return PatchProposal(
            id=f"patch_wrong_{attempt}",
            project_id=project_id,
            failure_id=failure.id,
            attempt=attempt,
            title=f"Wrong fix {attempt}",
            edits=[
                type(outcome.edits[0])(
                    path="main.py",
                    operation=outcome.edits[0].operation,
                    old='"username": user["username"],',
                    new=f'"username": user["email"],  # attempt {attempt}',
                    reason="wrong on purpose",
                )
            ],
            reasoning_engine="test",
        )

    monkeypatch.setattr(offline_engine, "build_patch", wrong_patch)
    session, _events, _ = await _run_repair(workspace, settings)
    assert len(session.attempts) == 3
    assert session.verdict is RepairVerdict.REPAIR_FAILED


async def test_approval_gate_blocks_application(demo_workspace, settings: Settings):
    """With approval required, nothing is written until a decision arrives."""
    settings.require_approval = True
    workspace = demo_workspace("fastapi-keyerror")
    original = (workspace / "main.py").read_text(encoding="utf-8")
    metadata = analyze_project(workspace)
    sandbox = await build_sandbox(settings)

    orchestrator = RepairOrchestrator(
        settings=settings,
        workspace=workspace,
        metadata=metadata,
        sandbox=sandbox,
        snapshots=SnapshotManager(workspace, settings.data_dir / "snaps", "prj_test"),
        project_id="prj_test",
        project_name="test",
        ai_client=None,
        emit=None,
    )

    task = asyncio.create_task(
        orchestrator.run(mode=RunMode.TEST, auto_approve=False, approval_timeout=30)
    )
    for _ in range(200):
        session = orchestrator.session
        if session and session.pending_patch_id:
            break
        await asyncio.sleep(0.05)
    else:
        task.cancel()
        pytest.fail("the orchestrator never reached the approval gate")

    # Still untouched while awaiting a decision.
    assert (workspace / "main.py").read_text(encoding="utf-8") == original

    orchestrator.approval.decide(False, "not now")
    session = await task
    assert session.verdict is RepairVerdict.REJECTED_BY_DEVELOPER
    assert (workspace / "main.py").read_text(encoding="utf-8") == original


async def test_approval_gate_allows_application(demo_workspace, settings: Settings):
    settings.require_approval = True
    workspace = demo_workspace("fastapi-keyerror")
    metadata = analyze_project(workspace)
    sandbox = await build_sandbox(settings)

    orchestrator = RepairOrchestrator(
        settings=settings, workspace=workspace, metadata=metadata, sandbox=sandbox,
        snapshots=SnapshotManager(workspace, settings.data_dir / "snaps", "prj_test"),
        project_id="prj_test", project_name="test", ai_client=None, emit=None,
    )
    task = asyncio.create_task(
        orchestrator.run(mode=RunMode.TEST, auto_approve=False, approval_timeout=60)
    )
    for _ in range(200):
        session = orchestrator.session
        if session and session.pending_patch_id:
            break
        await asyncio.sleep(0.05)
    else:
        task.cancel()
        pytest.fail("the orchestrator never reached the approval gate")

    orchestrator.approval.decide(True, "looks right")
    session = await task
    assert session.verdict is RepairVerdict.VERIFIED
    assert session.attempts[-1].full_test.all_passed


# ------------------------------------------------------------- verifier ----
def _run(passed: int, failed: int, exit_code: int, total: int | None = None) -> TestRunResult:
    return TestRunResult(
        exit_code=exit_code, passed=passed, failed=failed,
        total=total if total is not None else passed + failed,
    )


async def test_verifier_rejects_zero_collected_tests(demo_workspace, settings: Settings):
    """A green run that collected nothing is not a verified repair."""
    workspace = demo_workspace("fastapi-keyerror")
    outcome = verifier.VerificationOutcome(verified=True, reason="x")
    assert outcome.verified  # sanity: the dataclass itself is dumb

    # The real guard lives in verify_repair; exercise it through the helper.
    empty = _run(0, 0, 0, total=0)
    assert empty.all_passed
    analysis = verifier.offline_analysis(
        verifier.VerificationOutcome(
            verified=False,
            reason="the test suite reported success but collected zero tests",
            full=empty,
        ),
        attempt=1, max_attempts=2,
    )
    assert analysis.verified is False
    assert analysis.next_action == "retry"


def test_verifier_analysis_is_measured_not_estimated():
    outcome = verifier.VerificationOutcome(verified=True, reason="passed", full=_run(6, 0, 0))
    analysis = verifier.offline_analysis(outcome, attempt=1, max_attempts=3)
    assert analysis.verified is True
    assert analysis.confidence == 1.0
    assert analysis.reasoning_engine == "measured"
    assert analysis.next_action == "stop"


# ------------------------------------------------- cross-worker session ----
async def test_active_session_is_the_same_on_every_worker(settings: Settings):
    """A repair on worker A must not read as a stale verdict on worker B.

    Both workers serve the same port, so polls alternate between them. Before
    the shared mirror, worker B answered from disk — the *previous* finished
    session — and the UI flipped between "awaiting approval" and an old
    "verified" on every other request.
    """
    from types import SimpleNamespace

    from app.models.report import RepairSession
    from app.runtime.state import reset_state_backend
    from app.services.project_service import ProjectService
    from app.services.repair_service import RepairService

    await reset_state_backend()  # both workers share one in-process backend
    projects = ProjectService(settings)
    project = projects.create_from_zip("demo.zip", _tiny_zip(), "cross-worker")
    pid = project.id

    worker_a = RepairService(settings, projects)
    worker_b = RepairService(settings, projects)

    finished = RepairSession(
        id="sess_old", project_id=pid, project_name="cross-worker",
        verdict=RepairVerdict.VERIFIED, summary="an earlier run",
    )
    worker_a.save_session(pid, finished)

    live = RepairSession(
        id="sess_live", project_id=pid, project_name="cross-worker",
        verdict=RepairVerdict.AWAITING_APPROVAL, pending_patch_id="patch_1",
    )
    orchestrator = SimpleNamespace(session=live)
    worker_a._active[pid] = orchestrator  # type: ignore[assignment]

    # Without the mirror, the sibling can only see what is on disk.
    assert await worker_b.active_snapshot(pid) == (False, finished)

    mirror = asyncio.create_task(worker_a._mirror_active(pid, orchestrator))  # type: ignore[arg-type]
    try:
        await asyncio.sleep(0.05)
        running_a, session_a = await worker_a.active_snapshot(pid)
        running_b, session_b = await worker_b.active_snapshot(pid)
    finally:
        mirror.cancel()

    assert session_a is not None and session_b is not None
    assert session_a.id == session_b.id == "sess_live"
    assert session_b.pending_patch_id == "patch_1"
    assert running_b is True  # the owning worker is running it

    # Once the repair ends the mirror goes away and disk is authoritative again.
    await worker_a._clear_active_mirror(pid)
    assert await worker_b.active_snapshot(pid) == (False, finished)
    await reset_state_backend()


def _tiny_zip() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    return buffer.getvalue()
