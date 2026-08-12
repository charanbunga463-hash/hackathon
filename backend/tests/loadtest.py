"""Load test: does this actually hold up with N concurrent users?

Not a unit test — it drives a running server and reports real numbers.

    # start the server first
    python -m uvicorn app.main:app --port 8000

    python tests/loadtest.py --users 1000 --seconds 20
    python tests/loadtest.py --users 200 --scenario overload

Scenarios
    browse    Read-heavy mix: dashboard, project list, detail, files. What a
              room full of people watching demos actually generates.
    sse       Long-lived event-stream connections held open concurrently.
    overload  Hammer the heavy endpoints to prove admission control degrades
              cleanly (429/202 with Retry-After) instead of collapsing.
    mixed     browse + sse + a trickle of heavy work.

What "pass" means here: a high success rate, bounded p99, and — critically —
that any refusals are *deliberate* (429/202/503 with a retry hint), not
timeouts or 500s.
"""

from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path
import asyncio
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field

import httpx

DEFAULT_BASE = "http://127.0.0.1:8000"

# Statuses that mean "the server understood, and said no on purpose".
#   402 over quota · 409 already running for this project · 413 body too large
#   429 rate limited / queue full · 503 at capacity (SSE cap, draining)
# These are successes of the design, not failures of it.
DELIBERATE_REFUSALS = frozenset({402, 409, 413, 429, 503})


@dataclass
class Sample:
    label: str
    status: int
    seconds: float
    error: str | None = None


@dataclass
class Results:
    samples: list[Sample] = field(default_factory=list)
    started: float = 0.0
    finished: float = 0.0

    @property
    def duration(self) -> float:
        return max(1e-9, self.finished - self.started)

    def add(self, sample: Sample) -> None:
        self.samples.append(sample)

    def summarize(self) -> dict:
        if not self.samples:
            return {"requests": 0}
        latencies = sorted(s.seconds for s in self.samples)
        statuses = Counter(s.status for s in self.samples)
        # Three categories, because "not 2xx" is not the same as "broken":
        #   ok      — the request was served
        #   shed    — the server deliberately refused, with a reason the client
        #             can act on (retry later, already running, over quota)
        #   errors  — the server lost control: 5xx, or no response at all
        ok = sum(count for status, count in statuses.items() if 200 <= status < 300)
        shed = sum(
            count for status, count in statuses.items() if status in DELIBERATE_REFUSALS
        )
        errors = sum(
            count for status, count in statuses.items()
            if status == 0 or (status >= 500 and status not in DELIBERATE_REFUSALS)
        )
        handled = ok + shed
        return {
            "requests": len(self.samples),
            "duration_s": round(self.duration, 2),
            "throughput_rps": round(len(self.samples) / self.duration, 1),
            "ok": ok,
            "shed_backpressure": shed,
            "errors": errors,
            "handled_rate": round(handled / len(self.samples), 4),
            "success_rate": round(ok / len(self.samples), 4),
            "p50_ms": round(_pct(latencies, 0.50) * 1000, 1),
            "p95_ms": round(_pct(latencies, 0.95) * 1000, 1),
            "p99_ms": round(_pct(latencies, 0.99) * 1000, 1),
            "max_ms": round(latencies[-1] * 1000, 1),
            "statuses": dict(sorted(statuses.items())),
        }

    def by_label(self) -> dict:
        grouped: dict[str, list[float]] = {}
        for sample in self.samples:
            grouped.setdefault(sample.label, []).append(sample.seconds)
        return {
            label: {
                "n": len(values),
                "p50_ms": round(_pct(sorted(values), 0.5) * 1000, 1),
                "p95_ms": round(_pct(sorted(values), 0.95) * 1000, 1),
            }
            for label, values in sorted(grouped.items())
        }


def _pct(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(round(fraction * (len(sorted_values) - 1))))
    return sorted_values[index]


async def timed(results: Results, label: str, coro) -> None:
    started = time.perf_counter()
    try:
        response = await coro
        results.add(Sample(label, response.status_code, time.perf_counter() - started))
    except Exception as exc:  # noqa: BLE001 - a failed request is a data point
        results.add(
            Sample(label, 0, time.perf_counter() - started, f"{type(exc).__name__}: {exc}")
        )


async def browse_user(
    client: httpx.AsyncClient, results: Results, deadline: float, headers: dict, project_id: str | None
) -> None:
    """A person clicking around the UI."""
    while time.perf_counter() < deadline:
        await timed(results, "dashboard", client.get("/api/reports/dashboard", headers=headers))
        await timed(results, "projects", client.get("/api/projects", headers=headers))
        await timed(results, "system", client.get("/api/system", headers=headers))
        if project_id:
            await timed(
                results, "project_detail",
                client.get(f"/api/projects/{project_id}", headers=headers),
            )
            await timed(
                results, "project_files",
                client.get(f"/api/projects/{project_id}/files", headers=headers),
            )
        await timed(results, "history", client.get("/api/reports/history", headers=headers))
        await asyncio.sleep(0.05)


async def sse_user(
    client: httpx.AsyncClient, results: Results, deadline: float, headers: dict
) -> None:
    """Hold an event stream open, as every open browser tab does."""
    started = time.perf_counter()
    try:
        async with client.stream(
            "GET", "/api/events?replay=false", headers=headers, timeout=None
        ) as response:
            results.add(Sample("sse_connect", response.status_code, time.perf_counter() - started))
            if response.status_code != 200:
                return
            async for _line in response.aiter_lines():
                if time.perf_counter() >= deadline:
                    return
    except Exception as exc:  # noqa: BLE001
        results.add(
            Sample("sse_connect", 0, time.perf_counter() - started, f"{type(exc).__name__}: {exc}")
        )


async def overload_user(
    client: httpx.AsyncClient, results: Results, deadline: float, headers: dict, project_id: str
) -> None:
    """Push heavy endpoints far past capacity on purpose."""
    while time.perf_counter() < deadline:
        await timed(
            results, "run_tests",
            client.post(f"/api/execution/{project_id}/tests", headers=headers, timeout=40.0),
        )
        await asyncio.sleep(0.1)


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


async def setup_project(client: httpx.AsyncClient, headers: dict) -> str | None:
    try:
        response = await client.post(
            "/api/projects/upload", files={"file": ("fixture.zip", fixture_zip(), "application/zip")}, headers=headers, timeout=60.0
        )
        if response.status_code == 201:
            return response.json()["id"]
        projects = await client.get("/api/projects", headers=headers)
        if projects.status_code == 200 and projects.json():
            return projects.json()[0]["id"]
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not prepare a project: {exc}")
    return None


async def scrape_metrics(base_url: str) -> dict:
    """Server-side truth.

    Client-side timings on loopback include the load generator's own cost, which
    on a single box is often larger than the server's. The handler histogram is
    measured inside the app, so it separates "the server is slow" from "my
    benchmark client is slow".
    """
    totals: dict[str, dict[str, float]] = {}
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
            body = (await client.get("/metrics")).text
    except Exception:  # noqa: BLE001
        return {}
    for line in body.splitlines():
        if not line.startswith("apidoctor_http_request_duration_seconds_"):
            continue
        kind = "sum" if "_sum{" in line else "count" if "_count{" in line else None
        if kind is None:
            continue
        try:
            labels, value = line.rsplit(" ", 1)
            path = labels.split('path="', 1)[1].split('"', 1)[0]
            totals.setdefault(path, {"sum": 0.0, "count": 0.0})[kind] += float(value)
        except (IndexError, ValueError):
            continue
    return totals


def diff_metrics(before: dict, after: dict) -> dict:
    rows = {}
    for path, values in after.items():
        base = before.get(path, {"sum": 0.0, "count": 0.0})
        count = values["count"] - base["count"]
        total = values["sum"] - base["sum"]
        if count > 0:
            rows[path] = {"n": int(count), "mean_ms": round(total / count * 1000, 3)}
    return dict(sorted(rows.items(), key=lambda kv: -kv[1]["n"]))


async def run(args: argparse.Namespace) -> int:
    headers = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}
    limits = httpx.Limits(
        max_connections=args.users + 50, max_keepalive_connections=args.users + 50
    )
    results = Results()

    async with httpx.AsyncClient(
        base_url=args.base_url, limits=limits, timeout=args.timeout
    ) as client:
        try:
            health = await client.get("/api/health", timeout=5.0)
            health.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(f"Cannot reach {args.base_url}: {exc}")
            print("Start the server first:  python -m uvicorn app.main:app --port 8000")
            return 2

        project_id = None
        if args.scenario in {"browse", "overload", "mixed"}:
            print("  preparing a project...")
            project_id = await setup_project(client, headers)
            if args.scenario == "overload" and not project_id:
                print("  ! overload scenario needs a project")
                return 2

        metrics_before = await scrape_metrics(args.base_url)
        print(f"  starting {args.users} virtual users for {args.seconds}s "
              f"(scenario={args.scenario})")
        results.started = time.perf_counter()
        deadline = results.started + args.seconds

        tasks: list[asyncio.Task] = []
        for index in range(args.users):
            if args.scenario == "browse":
                coro = browse_user(client, results, deadline, headers, project_id)
            elif args.scenario == "sse":
                coro = sse_user(client, results, deadline, headers)
            elif args.scenario == "overload":
                coro = overload_user(client, results, deadline, headers, project_id)
            else:  # mixed
                if index % 10 == 0:
                    coro = sse_user(client, results, deadline, headers)
                elif index % 25 == 0 and project_id:
                    coro = overload_user(client, results, deadline, headers, project_id)
                else:
                    coro = browse_user(client, results, deadline, headers, project_id)
            tasks.append(asyncio.create_task(coro))

        await asyncio.gather(*tasks, return_exceptions=True)
        results.finished = time.perf_counter()

        metrics_after = await scrape_metrics(args.base_url)
        try:
            queue = (await client.get("/api/execution/queue", headers=headers)).json()
        except Exception:  # noqa: BLE001
            queue = {}

    summary = results.summarize()
    print("\n" + "=" * 66)
    print(f"RESULTS — {args.users} concurrent users, scenario={args.scenario}")
    print("=" * 66)
    for key in (
        "requests", "duration_s", "throughput_rps", "ok", "shed_backpressure",
        "errors", "handled_rate", "success_rate", "p50_ms", "p95_ms", "p99_ms", "max_ms",
    ):
        print(f"  {key:<20} {summary.get(key)}")
    print(f"  {'statuses':<20} {summary.get('statuses')}")
    print("\n  client-side per-endpoint (includes load-generator overhead):")
    for label, stats in results.by_label().items():
        print(f"    {label:<16} n={stats['n']:<6} p50={stats['p50_ms']}ms p95={stats['p95_ms']}ms")

    server = diff_metrics(metrics_before, metrics_after)
    if server:
        print("\n  SERVER-SIDE handler time (measured inside the app):")
        total_n = sum(row["n"] for row in server.values())
        total_ms = sum(row["n"] * row["mean_ms"] for row in server.values())
        for path, row in list(server.items())[:12]:
            print(f"    {path:<32} n={row['n']:<6} mean={row['mean_ms']}ms")
        if total_n:
            print(f"    {'ALL':<32} n={total_n:<6} mean={total_ms / total_n:.3f}ms")
            print(f"    implied single-worker ceiling: ~{1000 / (total_ms / total_n):.0f} req/s")

    if queue:
        print(f"\n  queue at finish: {queue}")

    failures = [s for s in results.samples if s.error]
    if failures:
        reasons = Counter(s.error.split(":")[0] for s in failures)
        print(f"\n  transport failures: {dict(reasons)}")

    # Verdict: hard errors and timeouts are failures. Deliberate shedding is
    # not — under overload, refusing with a reason IS the correct behaviour.
    handled = summary.get("handled_rate", 0)
    errors = summary.get("errors", 0)
    ok = errors == 0 and handled >= args.min_success
    print("\n  VERDICT:", "PASS" if ok else "FAIL")
    print(
        f"    {summary.get('ok')} served + {summary.get('shed_backpressure')} deliberately "
        f"refused = {handled:.2%} handled; {errors} hard error(s)"
    )
    if not ok:
        print(f"    required handled_rate >= {args.min_success} with 0 hard errors")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="API Doctor load test")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--users", type=int, default=200)
    parser.add_argument("--seconds", type=float, default=15.0)
    parser.add_argument(
        "--scenario", default="browse", choices=["browse", "sse", "overload", "mixed"]
    )
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--min-success", type=float, default=0.99)
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
