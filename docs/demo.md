# Demo script

A 5-minute walkthrough. The point to land is not "the AI fixed a bug" — it is **"the
system proved it fixed a bug, and would have told you if it hadn't."**

---

## Before you start

```bash
# terminal 1
cd backend && python -m uvicorn app.main:app --reload --port 8000

# terminal 2
cd frontend && npm run dev
```

Open <http://localhost:3000>.

Check **Settings** first and say out loud which engine is active. If `OPENAI_API_KEY` is
set it reads `openai` with the configured model; if not it reads `deterministic-offline`
and the UI labels every diagnosis that way. Either is a fine demo — just do not let the
audience think a rule engine is a model.

If Docker is not running you will see the amber **LOCAL TRUSTED MODE** banner on every
screen. That is the product telling the truth, not a bug. Mention it.

---

## 1 · Detect (60s)

**Projects → Upload ZIP → `demo-projects/fastapi-keyerror` zipped.**

The project is copied into an isolated workspace and statically analyzed: FastAPI, entry
point `main.py`, 4 routes, 1 test file.

Click **Run tests**.

```
4/6 passed, 2 failed, 0 errors in 3571 ms
```

> This is a real pytest subprocess. In Docker mode it ran in a container with 1 CPU,
> 512 MB, no network and a read-only root filesystem.

Open the **Failures** tab:

```
KeyError: 'username'
main.py:42 · tests/test_users.py::test_get_user
```

> Worth pausing on: pytest reported the failure inside the *test* file. The system walked
> the frames past every library frame to `main.py:42` — the application line that actually
> raised. That is what makes the next step possible.

## 2 · Diagnose (60s)

Click **Diagnose**. Read the panel top to bottom — it is deliberately laid out as a ladder:

- **OBSERVED FACT** — what was measured. `main.py:42 contains: "username": user["username"],`
- **HYPOTHESIS** — including one marked **REJECTED**, with the reason
- **ROOT CAUSE** — *"main.py:42 reads the dictionary key 'username', but the records it
  operates on are built with the key 'name'."*
- **Evidence** — each item badged **verified**, anchored to a real file and line

> Point at the green *verified* badges. Before this panel renders, every evidence item is
> checked against the workspace: the file must exist, the line must be within it, the test
> node id must be real. Anything that fails is **removed** and the diagnosis is flagged
> `some evidence dropped`. A model that invents `app/services/users.py:212` gets caught here.

Note the confidence number and that nothing has been written to the workspace — diagnosis
is read-only.

## 3 · Repair (90s)

Click **Repair**. Watch the right-hand **Agent activity** panel stream live over SSE:

```
get_stack_trace()          → KeyError: 'username'
inspect_project()          → fastapi project, 4 routes
read_file_range(main.py…)  → read main.py (lines 17-52)
inspect_tests(…)           → 1 test file(s)
search_code(query=username)→ 3 matches
diagnosis.ready            → root cause…
patch.validated            → Use the 'name' key instead of 'username'
patch.awaiting_approval    → Waiting for developer approval
```

The run **stops** at an approval gate showing the diff:

```diff
         "id": user["id"],
-        "username": user["username"],
+        "username": user["name"],
         "email": user["email"],
```

Two things to point out:

1. **One line.** The patch is capped by file count, edit count and changed-line budget. It
   cannot "refactor while it's in there".
2. **The response key `"username"` is untouched.** Only the *lookup* changed. Rewriting the
   response key would also make the test pass — and would silently change the API contract.

Say clearly: **nothing has been written to disk yet.** If you want to prove it, `git
status` the workspace, or just note the file still contains `user["username"]`.

Click **Apply patch**.

## 4 · Verify (60s)

```
targeted  1/1 passed, exit 0
full      6/6 passed, exit 0
FIX VERIFIED — 6/6 tests passed after the patch.
```

> This is the whole point. `FIX VERIFIED` is computed from the pytest exit code and a
> before/after comparison. The model is asked to *explain* the result; it cannot change it.
> There is no code path in this system that sets a verified verdict from model output.

If asked how it avoids cheating: the verifier also refuses to call a run verified when
zero tests were collected, or when **fewer** tests pass than before the patch. A suite that
goes green because tests disappeared is not a repair.

## 5 · The report (45s)

**History → the session.** The full investigation, in claim-ladder order: observed facts,
hypotheses (including rejected), root cause, evidence with excerpts, the diff, both test
runs with exit codes, the verdict, and a timeline. **Download Markdown** for the artefact.

The footer is the disclaimer, and it changes with the outcome:

> This verdict was produced by running the project's own test suite after the patch was
> applied. The pass/fail result is measured, not inferred.

---

## The demo that actually wins it: show a failure

Any agent demo can show a success. Show the honest failure.

**Option A — an unfixable bug (30s).** Load a demo, edit a test in the workspace to assert
something no mechanical fix can satisfy, and run a repair. You get:

```
REPAIR FAILED — the workspace was rolled back; your code is unchanged.
```

Not a hedge, not a partial success. And the file on disk is byte-identical to before.

**Option B — a wrong patch (built into the tests).**

```bash
cd backend && python -m pytest tests/test_repair_flow.py -q
```

`test_failed_verification_rolls_back` forces a plausible-but-wrong patch. The assertion is
that the verdict is `REPAIR_FAILED`, a `patch.rolled_back` event fired, and `main.py` on
disk is exactly what it was.

**Option C — reject the patch.** At the approval gate, click **Reject**. Verdict:
`REJECTED_BY_DEVELOPER`. Nothing written.

---

## The seven demos

| Demo | Bug class | Failing endpoint | What the fix must get right |
|---|---|---|---|
| `fastapi-keyerror` | `KeyError` | `GET /users/{id}` | change the lookup, not the response key |
| `fastapi-attribute-error` | `AttributeError` | `GET /sessions/{t}/expiry` | `.expiry` → `.expires_at` |
| `fastapi-billing` | `ZeroDivisionError` | `GET /carts/{id}/average` | guard the denominator, don't delete the endpoint |
| `fastapi-type-error` | `TypeError` | `GET /products/{sku}/gross-price` | coerce at point of use, don't mutate stored data |
| `fastapi-validation` | `ValidationError` | `GET /accounts/{u}/profile` | supply the missing field, don't make it optional |
| `fastapi-contract` | `ResponseValidationError` | `GET /books/{id}` | add the field, don't weaken `response_model` |
| `fastapi-http-error` | wrong status | `GET /orders/{id}` | raise `404`, don't change the test |

Run all seven through the real pipeline:

```bash
cd backend && python tests/run_repair_matrix.py
```

```
fastapi-attribute-error      VERIFIED  (1 attempt)
fastapi-billing              VERIFIED  (1 attempt)
fastapi-contract             VERIFIED  (1 attempt)
fastapi-http-error           VERIFIED  (1 attempt)
fastapi-keyerror             VERIFIED  (1 attempt)
fastapi-type-error           VERIFIED  (1 attempt)
fastapi-validation           VERIFIED  (1 attempt)

7/7 repairs verified by a real test run
```

---

## Likely questions

**"Is it just pattern-matching the demos?"** Upload your own broken FastAPI project as a
ZIP — it goes through the same hardened extraction. With an API key the model drives the
investigation with tools; the demos are fixtures for CI, not a lookup table.

**"What if it edits the tests to pass?"** Rejected by the validator with `modifies_tests`,
before the patch is ever shown. The prompt also states it, but the enforcement is code.

**"What stops it running `rm -rf`?"** There is no shell tool. The registry is fixed, the
backend implements each tool, and the only model-influenced argv value is a pytest node id
validated against an allowlist. Patches that *introduce* `os.system`/`subprocess`/`eval`
are refused.

**"How is this different from asking an LLM to fix it?"** The LLM is one component. Around
it: real execution, evidence grounding against the workspace, patch validation against
real bytes, an approval gate, snapshot/rollback, and a verdict computed from a test exit
code. Ask an LLM directly and you get a confident answer. Ask this and you get a verdict
with the receipts.

**"What if there's no API key?"** It runs a deterministic rule engine, labels it
`deterministic-offline` everywhere, and when no rule matches it says *"root cause not
determined"* with zero confidence rather than guessing.
