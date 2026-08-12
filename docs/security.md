# Security

## Threat model

API Doctor accepts a ZIP archive from a user and then **runs the code inside it**.
The uploaded project is hostile input, and so is anything a language model produces about
it.

Three adversaries are assumed:

1. **A malicious archive** — crafted to escape extraction, exhaust disk, or plant files.
2. **Malicious project code** — designed to read host secrets, reach the network, or
   consume the machine when executed.
3. **A model that is wrong or manipulated** — including prompt injection carried inside
   the project's own source, README or test output, which the agent necessarily reads.

Everything below is a control against one of these.

---

## 1. Archive extraction

`app/security/archive_security.py`. **`ZipFile.extractall` is never called.** Every member
is inspected before a byte is written.

| Attack | Control |
|---|---|
| `../../etc/cron.d/x` | `normalize_relative` rejects any `..` segment |
| `/etc/passwd` | absolute paths rejected |
| `C:\Windows\win.ini` | drive-qualified paths rejected |
| `\\server\share\x` | UNC paths rejected |
| Symlink → `/etc/shadow` | `S_IFLNK` in `external_attr` → rejected |
| Device/fifo/socket members | non-regular files rejected |
| Encrypted members | rejected (cannot be scanned) |
| Zip bomb (ratio) | compression ratio cap (default 120×) |
| Zip bomb (absolute) | total uncompressed budget (default 200 MB) |
| Oversized member | per-file cap (default 10 MB) |
| Too many members | file-count cap (default 5000) |
| Lying central directory | streamed write aborts if actual bytes exceed the declared size |

Containment is re-checked **after** joining each path, so case-folding and normalisation
tricks are caught too.

A ZIP upload is the only ingestion path: the service never fetches code from a remote
host, so there is no URL for a caller to point at an internal address.

## 2. Path containment

`app/security/path_security.py`. Every path from a model, an archive or an HTTP request is
normalised and re-checked for containment after resolution (so a symlinked escape is
caught, not just a textual `..`).

The write path adds policy on top:

- **protected files** — `.env`, `.env.*`, `id_rsa`, `id_ed25519`, `.netrc`, `.npmrc`, `.pypirc`
- **protected directories** — `.git/`, `.ssh/`, `.venv/`, `node_modules/`
- **forbidden types** — `.exe`, `.dll`, `.so`, `.pem`, `.key`, `.p12`, …
- symlinks and non-regular files are refused

## 3. Executing untrusted code

### Docker sandbox (preferred)

Every container from `app/execution/docker_runner.py`:

```
--network none              no network at all in TEST MODE
--cpus / --memory           hard resource caps (default 1.0 CPU / 512m)
--memory-swap = --memory    no swap escape hatch
--pids-limit                fork-bomb protection (default 128)
--cap-drop ALL              no privileged capabilities
--security-opt no-new-privileges
--read-only                 immutable root filesystem
--tmpfs /tmp:noexec,nosuid  small writable scratch
--user <uid>:<gid>          non-root (POSIX)
```

No host mount other than the project workspace. **No Docker socket.** No backend secrets.

The base image is built once with the runtime dependencies preinstalled, so a
`--network none` container can still run a FastAPI project. Uploaded `requirements.txt`
files are **never** `pip install`ed: that would execute arbitrary `setup.py` code. Missing
dependencies are reported as a diagnosable failure instead.

API MODE needs a published port, so it uses a bridge network with the port bound to
`127.0.0.1` only. This is stated in the sandbox capabilities rather than glossed over.

### LOCAL TRUSTED MODE (fallback)

Without Docker, project code runs on the host as the backend user. The only protections
are a hard timeout, a scrubbed environment, and never using a shell.

This is surfaced honestly:

- a persistent banner on **every** UI screen
- `GET /api/execution/sandbox` returns `isolated: false` with explicit warnings
- every repair session and report records `isolated_execution: false`
- `EXECUTION_MODE=docker` **refuses to start** rather than silently downgrading

We do not describe this mode as a sandbox.

### Isolation is probed, never assumed

The Docker CLI being on `PATH` does not mean the daemon is running. Reporting
"container isolated" on a machine where Docker Desktop has quit would be a false safety
claim — precisely the failure this product exists to avoid.

So every surface that mentions isolation derives it from a **successful sandbox build**,
not from configuration:

- `Settings.public_system_info()` is synchronous and cannot perform I/O, so it emits the
  safe values (`execution_mode_resolved: "local"`, `execution_isolated: false`) and
  exposes the configured intent separately as `execution_mode_intended`.
- `probe_execution_state()` builds the sandbox for real and overrides those fields.
  `GET /api/system` and `GET /api/execution/sandbox` both use it.
- The dashboard reports the sandbox actually used (`RepairService.sandbox_if_built()`),
  and `"not yet determined"` with `isolated_execution: false` before anything has run.

Guarded by `test_isolation_is_never_claimed_from_configuration_alone` and
`test_dashboard_does_not_claim_isolation_before_anything_has_run`.

## 4. Secrets

`app/security/execution_security.py`.

- `scrub_env()` builds child environments from an **allowlist**, not a denylist.
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, AWS/Azure/Google credentials,
  `DATABASE_URL` and anything matching `SECRET|TOKEN|PASSWORD|API_KEY|CREDENTIAL|PRIVATE_KEY`
  are removed.
- `assert_no_secrets()` raises **before** a process is spawned if any slipped through.
- Logs pass through a scrubbing formatter that redacts `sk-…` patterns and bearer tokens.
- No API route returns the key. `GET /api/system` returns `openai_key_hint` — a
  non-reversible `sk-...7890` fragment so an operator can tell *which* key is loaded.
- The key is never written into a generated or uploaded project file.

## 5. The model cannot execute anything

There is no `run_shell` tool and no code path that turns model output into a command line.

```
BAD   run_shell("rm -rf /")          ← does not exist
GOOD  run_full_tests()               ← fixed argv
      run_targeted_test(node_id)     ← node id validated against an allowlist
      read_file(path)                ← path containment enforced
      apply_patch(validated_patch)   ← backend-only, after approval
```

`apply_patch` and `rollback_patch` are **not exposed in the tool schema the model sees**.
Applying a change is gated on validation and developer approval and must not be reachable
by a model deciding to call a function. Tests assert both properties:

```
test_no_shell_tool_is_exposed
test_mutating_tools_are_not_exposed_to_the_model
```

The one model-influenced argv value — a pytest node id — must match
`^[A-Za-z0-9_\-./\[\]:=+ ]{1,300}$`, may not start with `-` (so it cannot smuggle a pytest
flag), and may not contain `..`.

## 6. Patch validation

Before a byte is written (`app/patches/patch_validator.py`):

1. **Path safety** — inside the workspace, not protected, not a symlink.
2. **Existence** — replace/insert require the file; create must not clobber.
3. **Anchor uniqueness** — `old` must occur exactly once. Zero means hallucinated code;
   more than one means an ambiguous edit. Both are hard failures.
4. **Blast radius** — file count, edit count and changed-line budgets.
5. **Syntax** — the post-edit content of every `.py` file must compile.
6. **Danger scan** — a patch that *introduces* `os.system`, `subprocess`, `eval`, `exec`,
   `__import__`, `pickle.loads`, `shutil.rmtree`, raw sockets, outbound HTTP calls or a
   credential reference is refused. A bug fix does not need any of these.
7. **Test files are never edited** — the tests define correct behaviour. A patch touching
   one is rejected with `modifies_tests`.

## 7. Applying and rolling back

Apply is all-or-nothing:

1. Re-validate (the workspace may have changed since approval).
2. Snapshot every affected file with its sha256, **outside** the workspace so project code
   cannot tamper with it.
3. Write atomically (temp file + `os.replace`).
4. Any failure mid-apply → immediate restore, then raise.

Rollback verifies each restored file's sha256 against the snapshot, and **deletes** files
the patch created. If a checksum mismatches, rollback reports failure rather than leaving
a half-reverted tree.

## 8. Prompt injection

The agent reads project source, README files and test output — all attacker-controlled.
The mitigations are structural rather than instructional:

- The model cannot execute commands, so injected instructions have nothing to drive.
- Tool arguments are validated by the backend regardless of why the model sent them.
- Patches are validated against real files and capped in size, so "now rewrite the whole
  auth module" cannot pass.
- Developer approval sits between any proposal and any write.
- Evidence is grounded against the workspace, so injected claims about non-existent files
  are dropped.

## 9. Denial of service

Timeouts on every subprocess with a guaranteed kill of the whole process tree (`taskkill
/T` on Windows, process-group kill on POSIX). Container CPU/memory/PID caps. Bounded
agent tool iterations. Bounded repair attempts. Output capture truncated with both ends
preserved. Bounded SSE queues. Snapshot pruning.

---

## Deployment notes

**Do not mount `/var/run/docker.sock`** into the backend container unless you understand
that it is root-equivalent on the host. It is commented out in `docker-compose.yml` with
that warning. Prefer running the backend on the host and containerising only the frontend.

There is no authentication on the API. It binds to `127.0.0.1` by default. Do not expose
it to a network without putting an authenticating reverse proxy in front of it — an
endpoint that runs uploaded code is not something to leave open.

## Reporting

Found a hole? Open an issue with reproduction steps. Please do not include real
credentials in the report.
