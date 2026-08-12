"""Prove multi-worker correctness against a running 4-worker deployment.

Two things break silently when you add workers without shared state, and both
are invisible in a single-worker demo:

  1. The developer's approval POST is load-balanced to a worker that is not
     running the orchestrator, so the patch never applies and the repair times
     out at the approval gate.
  2. An SSE client connected to worker C never sees events emitted by worker A,
     so the activity feed stays empty while work is happening.

This drives a real repair through a real multi-worker server and asserts both.

    python -m uvicorn app.main:app --workers 4 --port 8000   # with REDIS_URL set
    python tests/check_multiworker.py
"""

from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path
import asyncio
import json
import sys

import httpx

BASE = "http://127.0.0.1:8000"


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "demo-projects"


def fixture_zip(slug: str = "fastapi-keyerror") -> bytes:
    """Zip a fixture project so the script uploads it like a real user."""
    source = FIXTURE_ROOT / slug
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source.rglob("*")):
            if path.is_file() and path.name != "demo.json" and path.suffix != ".pyc":
                zf.write(path, path.relative_to(source).as_posix())
    return buffer.getvalue()


async def worker_ids(base: str, samples: int = 40) -> set[str]:
    """Fresh connections land on different workers; keep-alive would pin one."""
    seen: set[str] = set()
    for _ in range(samples):
        async with httpx.AsyncClient(base_url=base, timeout=10) as client:
            try:
                seen.add((await client.get("/api/execution/queue")).json()["worker"])
            except Exception:  # noqa: BLE001
                pass
    return seen


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE)
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()
    headers = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}

    async with httpx.AsyncClient(base_url=args.base_url, timeout=120) as client:
        ready = (await client.get("/readyz")).json()
        backend = ready.get("state_backend")
        print(f"state backend : {backend}")
        if backend != "redis":
            print("  ! REDIS_URL is not configured; multi-worker correctness cannot hold.")
            return 2

        workers = await worker_ids(args.base_url)
        print(f"workers seen  : {len(workers)} -> {sorted(workers)}")
        if len(workers) < 2:
            print("  ! only one worker answered; start with --workers 4")
            return 2

        # --- set up a project with a real failure --------------------------
        project = (
            await client.post(
                "/api/projects/upload",
                files={"file": ("multiworker-check.zip", fixture_zip(), "application/zip")},
                data={"name": "multiworker-check"},
                headers=headers,
            )
        ).json()
        project_id = project["id"]
        print(f"project       : {project_id}")

        run = await client.post(f"/api/execution/{project_id}/tests", headers=headers)
        print(f"baseline      : {run.json().get('label', run.status_code)}")

        # --- watch events on one connection (likely a different worker) ----
        seen_events: list[str] = []

        async def watch() -> None:
            try:
                async with httpx.AsyncClient(base_url=args.base_url, timeout=None) as watcher:
                    async with watcher.stream(
                        "GET", f"/api/events?project_id={project_id}&replay=false", headers=headers
                    ) as response:
                        async for line in response.aiter_lines():
                            if line.startswith("data:"):
                                try:
                                    seen_events.append(json.loads(line[5:].strip())["type"])
                                except Exception:  # noqa: BLE001
                                    pass
            except Exception:  # noqa: BLE001
                pass

        watcher_task = asyncio.create_task(watch())
        await asyncio.sleep(1.0)

        # --- start the repair; it runs on whichever worker accepted it -----
        started = await client.post(
            f"/api/repair/{project_id}/start", json={"mode": "test"}, headers=headers
        )
        print(f"repair start  : HTTP {started.status_code}")

        patch_id = None
        session_id = None
        for _ in range(120):
            await asyncio.sleep(1.0)
            active = (await client.get(f"/api/repair/{project_id}/active", headers=headers)).json()
            session = active.get("session") or {}
            session_id = session.get("id") or session_id
            if session.get("pending_patch_id"):
                patch_id = session["pending_patch_id"]
                break
            if session.get("verdict") not in (None, "pending", "awaiting_approval"):
                break
        if not patch_id:
            print("  ! never reached the approval gate")
            watcher_task.cancel()
            return 1
        print(f"awaiting gate : {patch_id}")

        # --- approve from a FRESH connection: different worker, very likely -
        async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as approver:
            decision = await approver.post(
                f"/api/repair/{project_id}/patch/{patch_id}/decision",
                json={"approve": True}, headers=headers,
            )
        print(f"approval sent : HTTP {decision.status_code}")

        verdict = None
        for _ in range(120):
            await asyncio.sleep(1.0)
            active = (await client.get(f"/api/repair/{project_id}/active", headers=headers)).json()
            session = active.get("session") or {}
            verdict = session.get("verdict")
            if verdict and verdict not in ("pending", "awaiting_approval"):
                break

        watcher_task.cancel()
        await asyncio.sleep(0.2)

        print(f"final verdict : {verdict}")
        print(f"events seen   : {len(seen_events)} -> {sorted(set(seen_events))[:8]}")

        ok_approval = verdict == "verified"
        ok_events = len(seen_events) > 0

        print()
        print(f"  cross-worker approval : {'PASS' if ok_approval else 'FAIL'}")
        print(f"  cross-worker events   : {'PASS' if ok_events else 'FAIL'}")
        return 0 if (ok_approval and ok_events) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
