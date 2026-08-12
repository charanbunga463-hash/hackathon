# Architecture

## The problem this shape solves

An agent that edits a developer's code has one failure mode that matters more than all
the others: **claiming a repair worked when it did not**. A wrong "I don't know" costs a
minute. A confident fabrication costs trust, and possibly a production incident.

Every structural decision below exists to make that failure mode hard to reach.

---

## Stage machine

There is exactly **one** orchestrator (`app/agents/orchestrator.py`). No agent spawns
another agent; no stage can skip ahead.

```
OBSERVE
  run pytest (TEST MODE) or start the API and probe it (API MODE)
  normalise every failure: error type, message, file, line, function, test, endpoint,
  status code, frames, severity
  ↓ no failures → NO_FAILURE_DETECTED (terminal, and not a success)

INVESTIGATE
  AI path      model drives a controlled tool loop over the real workspace
  offline path deterministic sweep ordered by the relevance ranker
  ↓

DIAGNOSE
  root cause + evidence + confidence + hypotheses (incl. rejected ones)
  ▸ GROUNDING CHECK — every evidence source must resolve to something real
  ↓

PLAN → GENERATE_PATCH
  smallest set of anchored edits
  ↓

VALIDATE_PATCH
  path safety · anchor uniqueness · syntax · blast radius · danger scan
  ↓ invalid → feed the validator errors back, regenerate once, else RETRY
  ↓

AWAIT_APPROVAL          (when REQUIRE_APPROVAL=true — the default)
  nothing has been written to disk yet
  ↓ rejected → REJECTED_BY_DEVELOPER (terminal)

APPLY
  snapshot → atomic writes → rollback on any failure
  ↓

VERIFY
  targeted tests, then the full suite
  ↓ pass  → VERIFIED       (terminal)
  ↓ fail  → ROLLBACK → post-mortem → RETRY (bounded) → REPAIR_FAILED
```

### Terminal verdicts

`RepairVerdict` is deliberately explicit. There is no ambiguous `success`:

`verified` · `repair_failed` · `patch_applied_unverified` · `awaiting_approval` ·
`rejected_by_developer` · `no_failure_detected` · `aborted` · `error` · `pending`

---

## Layers

| Layer | Package | Responsibility |
|---|---|---|
| Analysis | `app/analysis` | Parse the project and its output. Pure functions, no execution |
| Execution | `app/execution` | Run untrusted code under limits. No model input reaches a command line |
| AI | `app/ai` | The only place that talks to OpenAI |
| Agents | `app/agents` | Stage logic, prompts, tool registry, the offline engine |
| Patches | `app/patches` | Parse, validate, snapshot, apply, roll back |
| Security | `app/security` | Archive, path and execution policy |
| Services | `app/services` | Orchestration, persistence, the event bus |
| API | `app/api` | HTTP surface, SSE |

Dependencies point inward: `api → services → agents → {ai, analysis, execution, patches}
→ security/utils`. Nothing in `analysis` imports `ai`; nothing outside `ai` imports
`openai`.

---

## Key design decisions

### 1. Anchored replacements, not free-form diffs

A patch is a list of `(path, old, new)` edits where `old` must appear **exactly once** in
the target file.

```python
FileEdit(path="main.py", operation="replace",
         old='"username": user["username"],',
         new='"username": user["name"],')
```

Why not a unified diff? Because a diff's line numbers can be stale, and applying one
requires fuzz matching that succeeds *approximately*. An anchor either matches the real
bytes exactly once or it does not:

- **0 matches** → the model reconstructed code from memory. Reject.
- **2+ matches** → the edit is ambiguous. Reject.

This is what makes "apply safely" a guarantee rather than a hope. A unified-diff parser
exists in `patch_parser.py` purely as a fallback that converts to anchors.

### 2. The grounding check

An LLM will happily cite `app/services/users.py:212` in a project with no such file.
`agents/diagnostician.py` verifies every evidence item before it is shown:

- a file source must exist in the workspace
- a line number must be within that file
- a pytest node id must belong to a discovered test file
- an endpoint must match a discovered route

Failures are **removed**, listed in `ungrounded_evidence`, the diagnosis is marked
`grounded: false`, and confidence is capped. The UI shows that state rather than hiding
it.

### 3. Verification is measured, not asked

`agents/verifier.py` computes `verified` from the pytest exit code and a before/after
comparison. The model's `VerificationAnalysis` is collected for explanation and retry
guidance, and is explicitly allowed to be wrong.

Two extra guards catch "green for the wrong reason":

- a suite that passes having collected **zero tests** is not verified
- a suite that passes with **fewer passing tests than the baseline** is not verified —
  tests were removed or skipped, not fixed

### 4. Rollback before retry

A failed attempt is rolled back to its snapshot before the next one starts. Attempts
never compound edits, so attempt 3 reasons about the original code, and a run that ends
in `REPAIR_FAILED` leaves the workspace byte-identical to how it started.

### 5. The model cannot reach a shell

Tools are a fixed registry (`agents/tools.py`). The model chooses *which*; the backend
decides what each *does*. The only model-influenced value that reaches an argv is a
pytest node id, validated against a strict allowlist — and commands never go through a
shell.

`apply_patch`/`rollback_patch` are implemented for backend use but are **not in the
schema the model sees**, so no function call can bypass validation or approval.

### 6. Structured output, validated twice

Every stage requests a strict `json_schema` response format **and** re-validates the
payload against a Pydantic model. "The API said it was valid JSON" and "this is a patch I
will apply" are different claims. Invalid output → one corrective retry carrying the
validation errors → then stop safely.

### 7. Two failure detectors

- **TEST MODE** — run pytest. The project's own tests define correct behaviour.
- **API MODE** — start the app in the sandbox, read the live `/openapi.json`, call every
  discovered route, and mine the server log for the traceback behind a 500.

API mode catches what tests miss (a wrong status code that no test asserts); test mode
catches what probing misses (business logic).

### 8. Persistence behind an interface

`ProjectStore` is a `Protocol`; `JsonProjectStore` is the shipped implementation.

```
data/projects/<project_id>/
    project.json     metadata
    workspace/       the project's source — the only thing ever executed
    snapshots/       pre-patch file copies + sha256
    sessions/        repair session records
    executions/      test/probe run records
```

Moving to PostgreSQL means writing one more class, not touching routes or agents.

---

## Real-time activity

The orchestrator emits `AgentEvent`s at every stage. `EventBus` fans them out to SSE
subscribers with a bounded queue — a slow browser tab drops events rather than stalling
the repair loop — plus a replay buffer so a client connecting mid-run catches up.

The UI's activity stream reports `live` / `disconnected` truthfully rather than silently
showing stale data.

---

## Offline engine

With no `OPENAI_API_KEY`, `agents/offline_engine.py` provides a deterministic rule engine
covering the common Python API failure modes: KeyError, AttributeError, NameError,
numeric coercion TypeErrors, ZeroDivisionError, Pydantic missing-field, and missing
HTTPException.

It exists so the full pipeline can be exercised and tested in CI without credentials. It
is:

- tagged `reasoning_engine: "deterministic-offline"` everywhere
- labelled as not-AI in the API and on every UI surface
- **conservative** — when no rule matches it reports "root cause not determined" with zero
  confidence and proposes no patch

It feeds the same grounding check, the same validator and the same verifier as the AI
path, so the guarantees are identical regardless of which engine ran.
