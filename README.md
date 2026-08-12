# API Doctor

**Detect. Diagnose. Repair. Verify.**

An AI developer agent that detects broken APIs, investigates the failure against real
source code, logs, stack traces, tests and API contracts, identifies the root cause,
generates a minimal patch, validates it, applies it under developer approval, runs the
project's own tests, and reports whether the API was **actually** repaired.

Built for **PS-04 — AI Agent for Repairing Broken APIs**.

---

## The one rule this system will not break

> **A repair is reported as VERIFIED only when a real test run proves it.**

`VERIFIED` is computed from the pytest exit code and a before/after run comparison. The
model is asked to *explain* the result; it cannot change it. There is no code path that
sets a verified verdict from model output — and there is a test that asserts this.

Every claim the system makes is tagged with what kind of claim it is:

| Claim | Meaning |
|---|---|
| **OBSERVED FACT** | Measured from a run, or read from a file that exists |
| **HYPOTHESIS** | A candidate explanation, not yet established |
| **ROOT CAUSE** | The defect the evidence points to |
| **PROPOSED FIX** | A change that has not been applied or proven |
| **TEST RESULT** | The raw outcome of running the project's tests |
| **VERIFIED RESULT** | Proven by a real test run *after* the patch was applied |

The UI renders these distinctly, and the words "FIX VERIFIED" are emitted by exactly one
component, which requires a measured pass to do so.

---

## Worked example

```
OBSERVED   GET /users/1 returned HTTP 500.
           tests/test_users.py::test_get_user failed.
           KeyError was raised: 'username'.
           The exception surfaced at main.py:42.
           main.py:42 contains:  "username": user["username"],

HYPOTHESIS [REJECTED]  the data is missing 'username' for this record only
           [SUPPORTED] the code should read 'name', which is the key stored

ROOT CAUSE main.py:42 reads the dictionary key 'username', but the records it
           operates on are built with the key 'name'. The subscript therefore
           raises KeyError on every call.

PROPOSED   - "username": user["username"],
FIX        + "username": user["name"],

TEST       targeted  1/1 passed, exit 0
RESULT     full      6/6 passed, exit 0

VERIFIED   FIX VERIFIED — the full test suite passed: 6/6.
```

---

## Quick start

Requirements: **Python 3.12+**, **Node 20+**, and optionally **Docker** for the sandbox.

```bash
git clone <your-repo> api-doctor && cd api-doctor
cp .env.example .env        # add OPENAI_API_KEY (optional — see "Offline engine")
```

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

API docs: <http://localhost:8000/docs>

### Frontend

```bash
cd frontend
npm install
npm run dev
```

UI: <http://localhost:3000>

### Data stores

```
Postgres (Neon)  users · projects · repair sessions · execution records
Redis            sessions · one-time codes · rate limits · locks · pub/sub · cache
Disk             project workspaces and snapshots — the code the sandbox runs
```

Set `DATABASE_URL` to your Neon connection string and the schema migrates
itself at startup. Leave it empty and the app writes JSON files instead, which
is fine on a laptop and single-node only; production refuses to start without
it. Bringing an existing installation across:

```bash
cd backend && python scripts/migrate_json_to_postgres.py --dry-run
```

The migration is additive and idempotent — it upserts by id and deletes
nothing, so you can run it twice or fall back by unsetting `DATABASE_URL`.

### Or with Docker

```bash
docker compose up --build
```

Read the security note at the top of `docker-compose.yml` first — running the sandbox
from inside a container requires mounting the Docker socket, which is root-equivalent on
the host and is therefore **off by default**.

---

## See it work in 60 seconds

1. **Create an account.** Registration emails a six-digit code; with no SMTP host
   configured the code is written to the backend log instead
   (`docker compose logs -f backend`).
2. Upload a project **.zip** from **Projects** — `demo-projects/fastapi-keyerror` is a
   ready-made broken FastAPI app.
3. Click **Run tests** → `4/6 passed, 2 failed` and the failure is normalised to
   `KeyError: 'username' at main.py:42`.
4. Click **Repair**. Watch the agent stream its tool calls live.
5. It proposes a one-line patch and **waits for your approval**. Nothing has been written.
6. Approve → the patch is applied, targeted tests then the full suite run → **FIX VERIFIED**.
7. Open **History → the session** for the full investigation report, downloadable as Markdown.

Everything you upload is private to your account. A second account starts from an empty
dashboard and cannot see, open, repair or delete your projects.

`demo-projects/` holds seven intentionally broken FastAPI projects, each with a real
seeded defect. They are the test corpus — zip one and upload it to try the pipeline:

| Fixture | Bug class | Symptom |
|---|---|---|
| `fastapi-keyerror` | KeyError | `GET /users/{id}` → 500 |
| `fastapi-attribute-error` | AttributeError | `GET /sessions/{token}/expiry` → 500 |
| `fastapi-billing` | ZeroDivisionError | empty cart → 500 |
| `fastapi-type-error` | TypeError | CSV-imported price is a string |
| `fastapi-validation` | Pydantic ValidationError | required model field never supplied |
| `fastapi-contract` | ResponseValidationError | response omits a `response_model` field |
| `fastapi-http-error` | wrong HTTP status | missing order → `200 null` instead of `404` |

---

## Architecture

```
                    ┌─────────────────────────┐
                    │      NEXT.JS UI         │
                    │ Dashboard / Code / Diff │
                    └────────────┬────────────┘
                                 │  REST + SSE
                    ┌────────────▼────────────┐
                    │      FASTAPI API        │
                    └────────────┬────────────┘
             ┌───────────────────┼───────────────────┐
             ▼                   ▼                   ▼
      Project Analyzer       AI Agent            Execution
             │                   │                   │
             │                   ▼                   ▼
             │              OpenAI API           Sandbox
             ▼              (Responses)         (Docker)
        Source Code                              Tests/API
             └──────────────────┬────────────────────┘
                                ▼
                         Repair Engine
                    ┌───────────┴───────────┐
                    ▼                       ▼
                 Apply                   Rollback
                    │
                    ▼
                Verification
              ┌─────┴─────┐
              ▼           ▼
            PASS         FAIL
              │           │
              ▼           ▼
           VERIFIED    RETRY INVESTIGATION
```

The full stage machine lives in one place — `backend/app/agents/orchestrator.py`:

```
OBSERVE → INVESTIGATE → DIAGNOSE → PLAN → GENERATE_PATCH → VALIDATE_PATCH
        → [AWAIT_APPROVAL] → APPLY → VERIFY → (VERIFIED | RETRY | REPAIR_FAILED)
```

See [docs/architecture.md](docs/architecture.md).

---

## AI provider

**OpenAI only.** The official Python SDK, using the **Responses API** with structured
outputs.

- Every model call goes through `backend/app/ai/openai_client.py`. Nothing else in the
  codebase imports `openai`.
- Every stage requests a strict `json_schema` response format, and the payload is
  validated **again** against a Pydantic model before anything acts on it. Invalid output
  triggers one corrective retry that feeds the validation errors back; a second failure
  stops the run safely. Malformed model output is never applied.
- The model is chosen by `OPENAI_MODEL`. No model name is hard-coded at a call site. The
  configured model is shown on the Settings page.
- `OPENAI_API_KEY` is read from the environment only. It is never returned by any API
  route, never sent to the frontend, never logged, and is stripped from the environment of
  every sandboxed process.

### Agent tools

The model can request tools; it can never supply a command line.

```
list_files   read_file        read_file_range   search_code    find_symbol
inspect_project   inspect_tests   inspect_route   get_stack_trace
get_openapi_schema   run_targeted_test   run_full_tests   run_api_endpoint
validate_patch (dry run — writes nothing)
```

There is deliberately **no** `run_shell`. `apply_patch` and `rollback_patch` exist in the
backend but are **not exposed to the model** — applying a change is gated on validation
and developer approval, and must not be reachable by a model deciding to call a function.
A test asserts both of these.

### Offline engine

With no `OPENAI_API_KEY`, a deterministic rule engine runs instead so the whole pipeline
stays demoable and testable in CI. It is labelled `deterministic-offline` everywhere it
appears and is **never presented as model output**. When no rule matches it reports "root
cause not determined" with zero confidence rather than guessing.

---

## Safety

| Concern | What is done |
|---|---|
| Data at rest | Postgres (Neon) is the system of record; project workspaces stay on disk because the sandbox executes them. Redis holds only ephemera — sessions, one-time codes, rate limits — all of it TTL'd |
| Accounts | Argon2id password hashing, HttpOnly session cookies with idle + absolute expiry, emailed OTP verification stored only as an HMAC, per-IP rate limits on every auth endpoint, and identical responses for known and unknown addresses |
| ZIP uploads | No `extractall`. Every member is inspected first: traversal, absolute paths, drive letters, UNC, symlinks, non-regular files, encrypted members, per-file and total size budgets, member count, compression ratio |
| Path handling | Every model/user path is normalised and re-checked for containment after resolution; protected files (`.env`, keys, `.git/`) and binaries are refused |
| Executing project code | Docker sandbox: cpu/memory/pid caps, `--network none`, `--cap-drop ALL`, `no-new-privileges`, read-only rootfs, tmpfs `/tmp`, non-root user, no host mounts beyond the workspace |
| Secrets | `OPENAI_API_KEY` and every cloud credential are stripped from child process environments; a leak check raises before spawn; logs are scrubbed |
| Patches | Anchors must match exactly once; result must parse; blast-radius budgets; test files may not be edited; patches introducing `os.system`/`eval`/network calls are refused |
| Applying | Snapshot first, atomic writes, automatic rollback on any failure, verified restore by sha256 |

See [docs/security.md](docs/security.md).

### LOCAL TRUSTED MODE

Without Docker, project code runs on the host with only a timeout and a scrubbed
environment. The product says so on **every screen** with a persistent banner, and the
sandbox endpoint reports `isolated: false`. It does not claim isolation it does not have.

---

## Testing

```bash
cd backend
python -m pytest -q
```

**169 tests.** They cover archive and path attacks, secret scrubbing, traceback parsing
(including absolute Windows paths), route discovery, patch validation and rollback,
schema strictness, evidence grounding, and — most importantly — seven **end-to-end
repairs** that copy a real broken project, run real pytest subprocesses, apply real
patches and assert the workspace on disk is actually fixed.

Three tests exist specifically to stop this system lying:

- `test_unfixable_failure_reports_failure_not_success`
- `test_failed_verification_rolls_back`
- `test_verifier_analysis_is_measured_not_estimated`

Two harnesses for manual runs:

```bash
python tests/run_demo_matrix.py     # confirm every demo still fails as designed
python tests/run_repair_matrix.py   # run the full pipeline against every demo
```

---

## Layout

```
backend/app/
  ai/          openai_client.py · schemas.py · context_builder.py
  agents/      orchestrator · investigator · diagnostician · patch_generator
               verifier · offline_engine · tools · prompts/
  analysis/    project_analyzer · stacktrace_parser · log_analyzer · code_search
               dependency_analyzer · api_analyzer · relevance_ranker
  execution/   sandbox · docker_runner · local_runner · test_runner
               api_runner · process_manager
  patches/     patch_parser · patch_validator · patch_applier
               snapshot_manager · rollback_manager
  security/    archive_security · execution_security · path_security
  api/routes/  auth · projects · diagnosis · repair · execution
               reports · events · health
  db/          pool · migrations · stores (Neon Postgres)
frontend/      Next.js App Router · Tailwind · Recharts · SSE
demo-projects/ seven intentionally broken FastAPI projects (test fixtures)
docs/          architecture · security · api · demo
```

---

---

## Running it for real

Multi-tenant, multi-worker, with admission control:

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

| Concern | How it is handled |
|---|---|
| **Tenancy** | `AUTH_MODE=apikey`; every project is owned, every query scoped. A missing project and someone else's return the same 404 so ids cannot be enumerated |
| **Capacity** | Heavy jobs (containers, test suites) run behind a bounded queue: global + per-tenant concurrency, bounded backlog, `429`/`202` with `Retry-After` beyond it |
| **Multiple workers** | Redis-backed pub/sub carries approvals and events between workers. Without it, an approval landing on the wrong worker silently never applies |
| **Concurrency safety** | Distributed locks around read-modify-write; no lost counter updates |
| **Latency** | Nothing blocking on the event loop; single-flight caching on read aggregates |
| **Limits** | Per-tenant rate limits, project/storage quotas, body-size caps, SSE client cap |
| **Operations** | `/healthz`, `/readyz` (drains on shutdown), `/metrics`, correlation ids on every request and log line |

Production configuration is validated at startup — the app **refuses to boot**
with open auth, `EXECUTION_MODE=local`, wildcard CORS, weak API keys, or
multiple workers without Redis.

### Measured

1000 concurrent users, read-heavy mix, 4 workers + Redis on one 8-core box:

```
requests     7494        errors        0
throughput   246 rps     handled       100%
p50          2.0 s*      server-side   3.0 ms mean/request
```

\* client-side p50 includes the load generator, which was itself the bottleneck —
four client processes raised aggregate throughput to **436 rps** with no server
change. Overload behaves correctly too: 300 users hammering heavy endpoints
produced 100% handled, 0 errors, shedding via `409`/`429`.

```bash
python backend/tests/loadtest.py --users 1000 --seconds 20   # capacity
python backend/tests/loadtest.py --users 300 --scenario overload
python backend/tests/check_multiworker.py                    # cross-worker correctness
```

Full numbers, capacity planning and tuning: [docs/scaling.md](docs/scaling.md).

---

## Docs

- [docs/architecture.md](docs/architecture.md) — stages, data flow, design decisions
- [docs/security.md](docs/security.md) — threat model and every control
- [docs/scaling.md](docs/scaling.md) — measured capacity, multi-worker, tuning
- [docs/api.md](docs/api.md) — endpoint reference
- [docs/demo.md](docs/demo.md) — demo script and what to point at
