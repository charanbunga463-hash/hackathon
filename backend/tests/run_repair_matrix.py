"""Developer harness: run the full repair pipeline against every demo project.

This exercises the real system end to end — detect, investigate, diagnose,
patch, validate, apply, verify, roll back on failure — using whichever reasoning
engine is configured. Run it directly:

    python tests/run_repair_matrix.py
    python tests/run_repair_matrix.py fastapi-keyerror
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.orchestrator import RepairOrchestrator          # noqa: E402
from app.ai.openai_client import get_openai_client               # noqa: E402
from app.analysis.project_analyzer import analyze_project        # noqa: E402
from app.config.settings import Settings                         # noqa: E402
from app.execution.sandbox import build_sandbox                   # noqa: E402
from app.models.events import AgentEvent                          # noqa: E402
from app.models.execution import RunMode                          # noqa: E402
from app.patches.snapshot_manager import SnapshotManager          # noqa: E402
from app.utils.logging import configure_logging                   # noqa: E402

DEMOS = Path(__file__).resolve().parents[2] / "demo-projects"

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


async def repair_one(slug: str, *, verbose: bool = False) -> dict:
    source = DEMOS / slug
    scratch = Path(tempfile.mkdtemp(prefix=f"apidoctor-{slug}-"))
    workspace = scratch / "workspace"
    shutil.copytree(
        source, workspace,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "demo.json"),
    )

    settings = Settings(
        data_dir=scratch / "data",

        execution_mode=os.getenv("EXECUTION_MODE", "local"),
        require_approval=False,
        max_repair_attempts=int(os.getenv("MAX_REPAIR_ATTEMPTS", "2")),
    )
    settings.ensure_directories()
    metadata = analyze_project(workspace)
    sandbox = await build_sandbox(settings)

    events: list[AgentEvent] = []

    async def sink(event: AgentEvent) -> None:
        events.append(event)
        if verbose:
            print(f"  {DIM}{event.type.value:<28}{RESET} {event.message[:120]}")

    orchestrator = RepairOrchestrator(
        settings=settings,
        workspace=workspace,
        metadata=metadata,
        sandbox=sandbox,
        snapshots=SnapshotManager(workspace, scratch / "snapshots", slug),
        project_id=slug,
        project_name=slug,
        ai_client=get_openai_client(settings),
        emit=sink,
    )
    session = await orchestrator.run(mode=RunMode.TEST, auto_approve=True)

    last = session.attempts[-1] if session.attempts else None
    result = {
        "slug": slug,
        "verdict": session.verdict.value,
        "verified": session.verified,
        "engine": session.reasoning_engine,
        "runner": session.execution_runner,
        "attempts": len(session.attempts),
        "duration_ms": session.duration_ms,
        "failure": session.target_failure.headline() if session.target_failure else None,
        "root_cause": last.diagnosis.root_cause if last and last.diagnosis else None,
        "confidence": last.diagnosis.confidence if last and last.diagnosis else 0.0,
        "patch": last.patch.title if last and last.patch else None,
        "diff": (last.patch.diff if last and last.patch else "") or "",
        "baseline": session.baseline.summary_line() if session.baseline else None,
        "after": last.full_test.summary_line() if last and last.full_test else None,
        "summary": session.summary,
        "events": len(events),
        "workspace": str(workspace),
    }
    shutil.rmtree(scratch, ignore_errors=True)
    return result


async def main() -> int:
    configure_logging("WARNING")
    wanted = sys.argv[1:]
    slugs = [d.name for d in sorted(DEMOS.iterdir()) if d.is_dir()]
    if wanted:
        slugs = [s for s in slugs if s in wanted]
    verbose = len(slugs) == 1

    results = []
    for slug in slugs:
        print(f"\n{'=' * 78}\n{slug}\n{'=' * 78}")
        try:
            result = await repair_one(slug, verbose=verbose)
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            results.append({"slug": slug, "verdict": "harness_error", "verified": False,
                            "summary": str(exc), "attempts": 0})
            continue
        results.append(result)
        colour = GREEN if result["verified"] else RED
        print(f"  failure   : {result['failure']}")
        print(f"  baseline  : {result['baseline']}")
        print(f"  engine    : {result['engine']} / runner {result['runner']}")
        print(f"  root cause: {(result['root_cause'] or '(none)')[:150]}")
        print(f"  patch     : {result['patch']}")
        if verbose and result["diff"]:
            print("  diff:")
            for line in result["diff"].splitlines():
                print(f"    {line}")
        print(f"  after     : {result['after']}")
        print(f"  {colour}{result['verdict'].upper()}{RESET} in {result['attempts']} attempt(s), "
              f"{result['duration_ms']}ms")
        print(f"  {DIM}{result['summary']}{RESET}")

    print(f"\n{'=' * 78}\nSUMMARY\n{'=' * 78}")
    verified = 0
    for result in results:
        mark = f"{GREEN}VERIFIED{RESET}" if result["verified"] else f"{RED}{result['verdict']}{RESET}"
        verified += 1 if result["verified"] else 0
        print(f"  {result['slug']:<28} {mark}  ({result.get('attempts', 0)} attempt(s))")
    print(f"\n  {verified}/{len(results)} repairs verified by a real test run")
    return 0 if verified == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
