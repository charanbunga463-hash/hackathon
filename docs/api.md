# API reference

Base URL `http://localhost:8000` · all endpoints under `/api` · interactive docs at
`/docs`.

**Every endpoint requires an authenticated session** except the sign-in endpoints listed
under [Authentication](#authentication). The server binds to `127.0.0.1` by default — see
[security.md](security.md) before exposing it.

---

## Health & system

### `GET /api/health`
```json
{ "status": "ok", "app": "API Doctor", "env": "development", "time": "2026-08-10T17:21:32.980Z" }
```

### `GET /api/system`
Everything the Settings page shows. **Contains no credentials** — only
`openai_configured` and a non-reversible `openai_key_hint` (`"sk-...7890"`).

```json
{
  "ai_provider": "openai",
  "openai_model": "gpt-4o-mini",
  "openai_configured": false,
  "openai_key_hint": null,
  "reasoning_engine": "deterministic-offline",
  "execution_mode_configured": "auto",
  "execution_mode_intended": "docker",
  "execution_mode_resolved": "local",
  "execution_isolated": false,
  "docker_cli_present": true,
  "sandbox": { "kind": "local", "isolated": false, "warnings": ["No process isolation…"] },
  "sandbox_limits": { "cpus": 1.0, "memory": "512m", "pids": 128, "network": "none" },
  "upload_limits": { "max_project_size_mb": 50, "max_file_count": 5000 },
  "repair": { "max_attempts": 3, "require_approval": true }
}
```

#### Intended vs. actual execution mode

These three fields are deliberately distinct, and the difference is a safety claim:

| Field | Meaning |
|---|---|
| `execution_mode_configured` | The raw `EXECUTION_MODE` value (`auto`/`docker`/`local`) |
| `execution_mode_intended` | What that resolves to given the Docker **CLI** on `PATH` |
| `execution_mode_resolved` | The runner actually built, after **probing the daemon** |

The example above is a real one: Docker is installed (`docker_cli_present: true`) so the
intent is `docker`, but the daemon is not running, so the probe fell back to `local` and
`execution_isolated` is `false`.

**`execution_isolated` is only ever `true` when a sandbox was successfully built.** A
present CLI with a stopped daemon is never reported as isolation — see
`test_isolation_is_never_claimed_from_configuration_alone`.

`sandbox_limits` describes the limits that *would* apply in docker mode; `sandbox`
describes what is actually in force.

### `GET /api/system/ai`
Live provider probe. Never returns any part of the key.

```json
{ "ok": true, "configured": true, "model": "gpt-4o-mini", "detail": "ok",
  "latency_ms": 412, "provider": "openai", "active_engine": "openai" }
```

---

## Projects

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/projects` | List project summaries |
| `POST` | `/api/projects/upload` | Upload a `.zip` (multipart: `file`, optional `name`) |
| `GET` | `/api/projects/{id}` | Full project + metadata |
| `DELETE` | `/api/projects/{id}` | Delete project, workspace, snapshots, history |
| `POST` | `/api/projects/{id}/analyze` | Re-run static analysis |
| `GET` | `/api/projects/{id}/files` | Nested file tree |
| `GET` | `/api/projects/{id}/file?path=` | One file's content (path-contained) |
| `GET` | `/api/projects/{id}/routes` | Discovered API surface |

A `.zip` upload is the only way code enters the system. Upload analyzes on success and
returns the analyzed project.

```bash
curl -F "file=@project.zip" http://localhost:8000/api/projects/upload
```

`400` on a rejected archive, with the specific reason:
```json
{ "detail": "unsafe archive member '../../x.py': path traversal is not allowed" }
```

**ProjectMetadata** carries `language`, `framework`, `entry_point`, `app_object`,
`test_framework`, `test_files`, `test_details`, `routes`, `dependencies`, `source_files`,
`config_files` and analyzer `notes`.

---

## Execution

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/execution/sandbox` | Runner capabilities and isolation status |
| `POST` | `/api/execution/{id}/run` | Run in a chosen mode (`{"mode":"test"\|"api"}`) |
| `POST` | `/api/execution/{id}/tests` | TEST MODE — run pytest |
| `POST` | `/api/execution/{id}/probe` | API MODE — start the app and call its endpoints |
| `GET` | `/api/execution/{id}/history` | Recent execution records |
| `GET` | `/api/execution/{id}/latest` | Most recent record |

`GET /api/execution/sandbox` is the honest-isolation endpoint:

```json
{ "kind": "local", "isolated": false, "network": "host (unrestricted)",
  "trusted_mode_banner": "LOCAL TRUSTED MODE — uploaded code runs on the host without isolation.",
  "warnings": ["No process isolation…", "No network restriction…"] }
```

An **ExecutionRecord** contains `runner`, `isolated`, `failure_count`, `healthy` and
either `test_result` or `api_result`.

**TestRunResult** — `exit_code`, `passed`, `failed`, `errors`, `skipped`, `total`,
`duration_ms`, `stdout`, `stderr`, `timed_out`, `collection_error`, `cases[]`, `failures[]`.

**NormalizedFailure**:
```json
{
  "id": "fail_9c1d2b3a4e5f",
  "error_type": "KeyError",
  "message": "'username'",
  "file": "main.py",
  "line": 42,
  "function": "get_user",
  "test": "tests/test_users.py::test_get_user",
  "endpoint": null,
  "status_code": null,
  "severity": "high",
  "source": "pytest",
  "frames": [{ "file": "main.py", "line": 42, "in_project": true }]
}
```

---

## Diagnosis

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/diagnosis/{id}/failures` | Failures from the latest run |
| `POST` | `/api/diagnosis/{id}` | Investigate and diagnose — **read-only** |

`POST` body: `{"failure_id": "fail_… "}` (optional; defaults to the first failure).
Nothing is written to the workspace — a test asserts this.

```json
{
  "diagnosis": {
    "summary": "…", "root_cause": "…", "confidence": 0.9,
    "evidence": [{ "kind": "source_code", "source": "main.py", "line": 42,
                   "detail": "…", "excerpt": "\"username\": user[\"username\"],",
                   "verified": true }],
    "affected_files": [{ "path": "main.py", "line_start": 42, "line_end": 42 }],
    "severity": "high",
    "hypotheses": [{ "statement": "…", "status": "rejected", "confidence": 0.15 }],
    "reasoning_engine": "deterministic-offline",
    "grounded": true,
    "ungrounded_evidence": []
  },
  "observed_facts": ["…"],
  "reasoning_engine": "deterministic-offline",
  "note": "OPENAI_API_KEY is not configured, so this diagnosis came from the deterministic rule engine rather than a model."
}
```

`grounded: false` plus a populated `ungrounded_evidence` means the model cited things that
do not exist; those items were removed and confidence was capped.

`409` when the latest run found no failures.

---

## Repair

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/repair/{id}/start` | Start a session (returns immediately) |
| `GET` | `/api/repair/{id}/active` | Current session + `running` flag |
| `POST` | `/api/repair/{id}/patch/{patch_id}/decision` | **Approval gate** |
| `POST` | `/api/repair/{id}/cancel` | Cancel a running repair |
| `GET` | `/api/repair/{id}/sessions` | Session summaries |
| `GET` | `/api/repair/{id}/sessions/{sid}` | Full session |
| `POST` | `/api/repair/{id}/sessions/{sid}/rollback` | Undo an applied patch |
| `GET` | `/api/repair/{id}/snapshots` | Snapshots taken before patches |
| `POST` | `/api/repair/{id}/snapshots/{snap}/restore` | Restore a snapshot |

```bash
curl -X POST http://localhost:8000/api/repair/prj_abc/start \
  -H 'Content-Type: application/json' \
  -d '{"mode":"test","failure_id":null,"auto_approve":null}'
```

`auto_approve: null` uses the server default (`REQUIRE_APPROVAL`). `true` skips the gate —
for CI and demos only.

Poll `/active` until `session.pending_patch_id` appears, then decide:

```bash
curl -X POST http://localhost:8000/api/repair/prj_abc/patch/patch_xyz/decision \
  -H 'Content-Type: application/json' -d '{"approve":true}'
```

`409` if that patch is not the one awaiting approval.

**RepairSession** — `stage`, `verdict`, `baseline`, `baseline_failures`, `target_failure`,
`attempts[]`, `max_attempts`, `require_approval`, `pending_patch_id`, `summary`,
`reasoning_engine`, `execution_runner`, `isolated_execution`, `duration_ms`.

Each **RepairAttempt** — `investigation`, `diagnosis`, `plan`, `patch`, `validation`,
`applied`, `targeted_test`, `full_test`, `verification`, `verified`, `outcome`,
`rolled_back`.

**Verdicts**: `verified` · `repair_failed` · `patch_applied_unverified` ·
`awaiting_approval` · `rejected_by_developer` · `no_failure_detected` · `aborted` ·
`error` · `pending`.

---

## Reports

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/reports/dashboard` | Stats + recent failures + system info |
| `GET` | `/api/reports/history` | All sessions, newest first |
| `GET` | `/api/reports/sessions/{sid}` | Full investigation report |
| `GET` | `/api/reports/sessions/{sid}/markdown` | The same report as a download |

The report is structured around the claim ladder:

```json
{
  "headline": "FIX VERIFIED",
  "verified": true,
  "observed_facts": ["Baseline test run: 4/6 passed, 2 failed…"],
  "hypotheses": ["[REJECTED] …", "[SUPPORTED] …"],
  "root_cause": "main.py:42 reads the dictionary key 'username'…",
  "evidence": [{ "source": "main.py", "line": 42, "verified": true, "excerpt": "…" }],
  "proposed_fix": "Use the 'name' key instead of 'username' — …",
  "diff": "--- a/main.py\n+++ b/main.py\n@@ …",
  "test_results": [{ "attempt": 1, "scope": "full", "summary": "6/6 passed…", "exit_code": 0 }],
  "verification": { "verified": true, "original_failure_resolved": true, "regressions_introduced": false },
  "timeline": [{ "at": "…", "stage": "verify", "detail": "Full suite: 6/6 passed" }],
  "disclaimer": "This verdict was produced by running the project's own test suite…"
}
```

`headline` is derived from the measured verdict, never from prose.

---

## Authentication

Every endpoint below except these requires a session cookie; without one the API answers
`401`. The cookie is HttpOnly, so it is set and cleared by the server and is never
readable from JavaScript.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/auth/config` | What the sign-in UI needs (no secrets) |
| `POST` | `/api/auth/register` | Create an account and email a verification code |
| `POST` | `/api/auth/verify-otp` | Confirm the address; signs the user in |
| `POST` | `/api/auth/resend-otp` | Send a fresh code (`purpose`: `verify` or `reset`) |
| `POST` | `/api/auth/login` | Sign in |
| `POST` | `/api/auth/logout` | Revoke the session server-side |
| `GET` | `/api/auth/me` | The signed-in account |
| `POST` | `/api/auth/forgot-password` | Email a reset code |
| `POST` | `/api/auth/verify-reset-otp` | Exchange a reset code for a single-use ticket |
| `POST` | `/api/auth/reset-password` | Set a new password using that ticket |

```bash
curl -c jar -X POST http://localhost:8000/api/auth/login   -H 'Content-Type: application/json'   -d '{"email":"you@example.com","password":"your-password"}'

curl -b jar http://localhost:8000/api/projects
```

The one-time code is never in a response body — only in the email. `register` and
`forgot-password` answer identically whether or not the address is registered, so
neither can be used to discover who has an account.

## Events (SSE)

### `GET /api/events?project_id=&session_id=&replay=true`

`text/event-stream`. Each frame is named after its event type:

```
event: patch.applied
data: {"id":42,"type":"patch.applied","level":"success","message":"Applied patch to main.py",
       "at":"2026-08-10T17:23:02.140Z","project_id":"prj_abc","session_id":"sess_xyz",
       "stage":"apply","attempt":1,"data":{"files":["main.py"],"snapshot_id":"snap_…"}}
```

A `: heartbeat` comment every 15s keeps proxies from closing the stream.

**Event types**: `session.started` `session.finished` `stage.started` `stage.finished`
`project.created` `project.analyzed` `project.deleted` `execution.started`
`execution.finished` `failure.detected` `failure.none` `agent.thinking`
`agent.tool_call` `agent.tool_result` `agent.message` `diagnosis.ready` `plan.ready`
`patch.proposed` `patch.validated` `patch.rejected` `patch.awaiting_approval`
`patch.applied` `patch.rolled_back` `verification.started` `verification.passed`
`verification.failed` `retry.scheduled` `warning` `error` `heartbeat`

### `GET /api/events/history`
Replay buffer as JSON, for clients that cannot hold a stream open.

---

## Errors

| Status | Meaning |
|---|---|
| `400` | Bad input, or a rejected archive/path/URL — `detail` says exactly why |
| `404` | Unknown project, file, session or demo |
| `409` | Conflicting state (repair already running, no failures to diagnose, wrong patch id) |
| `503` | `EXECUTION_MODE=docker` but the daemon is unreachable |

All errors: `{ "detail": "human-readable reason" }`.
