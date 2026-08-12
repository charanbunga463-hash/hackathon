# Scaling and capacity

## The distinction that governs everything

**1000 concurrent users** is an architecture problem — mostly reads, streams and
polling. Solved with non-blocking handlers, caching and more workers.

**1000 concurrent repairs** is a capacity problem. One repair starts containers
and runs a real test suite: seconds to minutes of CPU, hundreds of MB of RAM. No
code change makes 1000 of those run at once on one box. They are queued, and
users are told where they stand.

Conflating the two is how systems get promised as "handles 1000 users" and then
fall over. API Doctor treats them separately.

---

## Measured results

Single box, Windows 11, 8 logical cores. Load generator on the same machine
(`backend/tests/loadtest.py`), which matters — see the caveat below.

### 1000 concurrent users, read-heavy browse mix

| Configuration | Throughput | Errors | Success | Client p50 |
|---|---|---|---|---|
| Baseline (before this work) | 63 rps | **1340** | 77.7% | 7660 ms |
| + response caching, larger pools | 136 rps | 0 | 100% | 3415 ms |
| + pure-ASGI middleware | 233 rps | 0 | 100% | 2045 ms |
| + 4 workers & Redis | 280 rps | 0 | 100% | 1789 ms |
| 4 workers, 4 client processes | **436 rps** | 0¹ | 100% | — |

¹ 27 client-side connection errors from ephemeral-port pressure on the load
generator. The server recorded **zero** non-2xx responses across the run
(verified from `/metrics`).

### Server-side handler time

Measured *inside* the app by the metrics histogram, so it excludes the load
generator's own cost:

| Endpoint | Mean (1 worker) | Mean (4 workers) |
|---|---|---|
| `/api/reports/dashboard` | 16.3 ms | 5.8 ms |
| `/api/reports/history` | 3.4 ms | 2.6 ms |
| `/api/projects/{id}/files` | 3.0 ms | 2.3 ms |
| `/api/projects/{id}` | 2.8 ms | 2.1 ms |
| `/api/projects` | 1.9 ms | 1.5 ms |
| `/api/system` | 1.5 ms | 1.3 ms |
| **All** | **4.8 ms** | **2.6 ms** |
| `/healthz` (empty handler) | 0.35 ms | — |

**Caveat, stated plainly:** the load generator is a single Python process on the
same machine, so client-side p50/p95 include its own overhead and are a *floor*,
not the server's ceiling. Running four client processes raised aggregate
throughput from 280 to 436 rps with no change to the server, which demonstrates
the client was the constraint. For a real capacity number, drive load from
separate machines. The server-side histogram is the honest signal here.

### What actually moved the needle

1. **Single-flight caching of read aggregates** — the dashboard scanned every
   session file per request; 1000 concurrent viewers meant 1000 identical disk
   scans. Coalescing them into one scan per TTL eliminated all 1340 errors and
   doubled throughput. Biggest single win.
2. **Pure-ASGI middleware** — four `BaseHTTPMiddleware` layers each wrap every
   request in an anyio task group. A trivial `/healthz` peaked at 696 rps and
   *degraded* to 259 rps at concurrency 64. Rewriting as pure ASGI removed the
   degradation.
3. **Offloading blocking work** — AST analysis and disk scans ran inline in
   `async def` handlers, stalling every other request on that worker.
4. **More workers** — after the above, per-request cost is the limit, and
   workers scale it.

---

## Capacity planning

Start from measured cost per request:

```
requests/sec per worker  ≈  1000 / mean_handler_ms
                         ≈  1000 / 2.6  ≈  385 rps   (measured, 4-worker mix)
```

For a target of **1000 concurrent users** on a browse-style workload:

| Assumption | Value |
|---|---|
| Requests per user per minute | ~12 (UI polls every 5–8 s) |
| Offered load | 1000 × 12 / 60 = **200 rps** |
| Per-worker capacity | ~385 rps |
| Workers needed for headroom (×3) | **2 replicas × 4 workers** |

Heavy work is sized separately and independently:

```
MAX_CONCURRENT_JOBS  ≈  cores available for sandboxes
```

A repair takes 3–40 s. With `MAX_CONCURRENT_JOBS=4`, sustained throughput is
roughly 6–80 repairs/minute. Beyond that, users queue — which is the correct
behaviour, and the queue tells them their position.

---

## Deploying more than one worker

**Multiple workers require `REDIS_URL`.** Without it each worker has private
in-memory state, and two things break silently:

1. A developer's approval POST is load-balanced to a worker that is not running
   the orchestrator. The patch never applies; the repair sits at the gate.
2. An SSE client on worker C never sees events emitted by worker A. The activity
   feed stays empty while work happens.

Both are silent — no error, no log, just nothing happening. The app logs an
error at startup if it sees `WEB_CONCURRENCY > 1` without Redis, and
`Settings.validate_for_environment()` refuses to start in production.

Verify a real deployment:

```bash
python backend/tests/check_multiworker.py
```

It drives a real repair against a running multi-worker server, sends the
approval on a **fresh connection** (so it lands on a different worker), and
asserts both the approval and the event stream crossed workers:

```
state backend : redis
workers seen  : 4 -> ['w-43db3f5c', 'w-6165a8be', 'w-c3a5b778', 'w-cc2afc88']
baseline      : 4/6 passed, 2 failed, 0 errors in 3489 ms
awaiting gate : patch_77586a34f5cc
approval sent : HTTP 200
final verdict : verified
events seen   : 30

  cross-worker approval : PASS
  cross-worker events   : PASS
```

### Platform note: subprocesses and workers

On Windows, uvicorn's multi-worker mode gives workers an event loop whose
`create_subprocess_exec` raises `NotImplementedError` — so **every sandboxed test
run fails the moment you scale past one worker**. `process_manager.run_process`
detects this and falls back to a threaded runner with identical semantics
(regression-tested in `test_runtime.py`). API MODE still needs a real child
process with streamed output, so it reports a clear error instead; use TEST
mode, a single worker, or a Linux container.

---

## Behaviour under overload

The system sheds load deliberately rather than degrading everywhere:

| Condition | Response |
|---|---|
| Job queue full | `429` + `Retry-After` |
| Tenant at its queued-job limit | `429` + `Retry-After` |
| Rate limit exceeded | `429` + `Retry-After` + `X-RateLimit-*` |
| Job slower than the inline wait | `202` + `job_id` + `status_url` |
| SSE client cap reached | `503` + `Retry-After` |
| Body over the size limit | `413` |
| Tenant over quota | `402` |
| Draining for shutdown | `readyz` → `503`, in-flight jobs finish |

The reasoning: accepting work you cannot finish means *everyone* times out.
Refusing some work means most requests succeed and the rest get a clear,
actionable answer.

Confirm it holds:

```bash
python backend/tests/loadtest.py --users 200 --scenario overload
```

---

## Tuning

| Setting | Default | Raise when | Lower when |
|---|---|---|---|
| `WEB_CONCURRENCY` | 4 | CPU is idle and latency is rising | Memory-bound |
| `MAX_CONCURRENT_JOBS` | 4 | Sandbox hosts have spare cores | Repairs are timing out |
| `MAX_CONCURRENT_JOBS_PER_TENANT` | 1 | Single-tenant deployment | One tenant is starving others |
| `MAX_QUEUED_JOBS` | 200 | Bursty traffic, patient users | You would rather fail fast |
| `AGGREGATE_CACHE_SECONDS` | 2.0 | Read-heavy, many viewers | Users need instant write visibility |
| `IO_POOL_WORKERS` | 8×cores | Disk-bound with idle CPU | Thrashing on a slow disk |
| `MAX_SSE_CLIENTS` | 1000 | More memory available | Memory pressure |

---

## What to watch

Scrape `/metrics` from **every worker** — each keeps its own counters, so a
single scrape of a load-balanced endpoint sees roughly `1/N` of traffic. (That
is exactly why the 4-worker load test recorded 1787 of 8538 requests.)

| Metric | Meaning | Act when |
|---|---|---|
| `apidoctor_http_request_duration_seconds` | Handler latency | p99 rising → add workers |
| `apidoctor_job_queue_depth` | Jobs waiting | Persistently > 0 → add capacity |
| `apidoctor_jobs_rejected_total` | Refused by admission control | Growing → users are being turned away |
| `apidoctor_jobs_total{status="failed"}` | Failed repairs | Spike → investigate the sandbox |
| `apidoctor_http_in_flight` | Concurrent requests | Near worker capacity → scale out |
| `apidoctor_sse_clients` | Open streams | Near `MAX_SSE_CLIENTS` → scale out |
| `apidoctor_rate_limited_total` | Throttled requests | Growing → limits may be too tight |

---

## Known limits

- **Storage is the filesystem.** Workspaces are on a shared volume, so replicas
  need shared storage (NFS/EFS) or affinity to one node. `ProjectStore` is a
  Protocol precisely so a database/object-store implementation can replace it.
- **Jobs run on the worker that accepted them.** State is shared, so status and
  approvals work across workers, but there is no central broker redistributing
  queued work. A worker dying loses its in-flight jobs (rolled back on restart,
  because patches snapshot before applying).
- **`/metrics` is per worker.** Aggregate in Prometheus, not from one scrape.
- **No horizontal autoscaling logic.** `job_queue_depth` is the signal to use.
