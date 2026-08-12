"""The agent's tool registry.

The model can *request* a tool by name with JSON arguments. It cannot supply a
command line, a shell string, a path outside the workspace, or a pytest flag.
Each tool below is a fixed backend implementation; the model's arguments are
validated before anything runs.

There is deliberately no `run_shell` tool. If you are extending this file,
adding one would defeat the entire security model.

Mutating tools (`apply_patch`, `rollback_patch`) are implemented here because
the backend uses the same registry, but they are NOT exposed in the schema the
model sees during investigation — applying a patch is gated on validation and
developer approval in the orchestrator, and must not be reachable by a model
deciding to call a function.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..analysis.api_analyzer import concretize_path
from ..analysis.code_search import (
    enclosing_symbol,
    find_symbol_definitions,
    search_code,
)
from ..analysis.project_analyzer import build_file_tree
from ..config.settings import Settings
from ..execution.sandbox import Sandbox
from ..execution.test_runner import run_tests
from ..models.execution import NormalizedFailure, TestRunResult
from ..models.project import ProjectMetadata
from ..security.execution_security import ExecutionSecurityError, validate_test_selector
from ..security.path_security import PathSecurityError, safe_join
from ..utils.filesystem import iter_files, numbered_slice, read_text, relative_posix
from ..utils.logging import get_logger

logger = get_logger(__name__)

MAX_READ_CHARS = 20000
MAX_SEARCH_RESULTS = 25


@dataclass
class ToolContext:
    """Everything the tools are allowed to touch."""

    workspace: Path
    metadata: ProjectMetadata
    settings: Settings
    sandbox: Sandbox
    failure: NormalizedFailure | None = None
    openapi: dict | None = None
    baseline: TestRunResult | None = None
    on_test_run: Callable[[TestRunResult], Awaitable[None]] | None = None


def _error(message: str) -> dict:
    return {"error": message}


# ---------------------------------------------------------------------------
# Read-only inspection tools
# ---------------------------------------------------------------------------


async def tool_list_files(ctx: ToolContext, args: dict) -> dict:
    subdir = str(args.get("directory") or "").strip()
    pattern = str(args.get("pattern") or "").strip().lower()
    root = ctx.workspace
    if subdir and subdir not in {".", "/"}:
        try:
            root = safe_join(ctx.workspace, subdir)
        except PathSecurityError as exc:
            return _error(str(exc))
        if not root.exists() or not root.is_dir():
            return _error(f"directory not found: {subdir}")
    files = []
    for path in iter_files(root):
        relative = relative_posix(path, ctx.workspace)
        if pattern and pattern not in relative.lower():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        files.append({"path": relative, "size": size})
        if len(files) >= 400:
            break
    return {"directory": subdir or ".", "count": len(files), "files": files}


async def tool_read_file(ctx: ToolContext, args: dict) -> dict:
    raw_path = args.get("path")
    if not raw_path:
        return _error("'path' is required")
    try:
        target = safe_join(ctx.workspace, str(raw_path))
    except PathSecurityError as exc:
        return _error(str(exc))
    if not target.exists() or not target.is_file():
        return _error(f"file not found in the workspace: {raw_path}")
    content = read_text(target)
    total = len(content.splitlines())
    truncated = len(content) > MAX_READ_CHARS
    return {
        "path": str(raw_path).replace("\\", "/"),
        "total_lines": total,
        "truncated": truncated,
        "content": numbered_slice(content, 1, min(total, 500))[:MAX_READ_CHARS],
    }


async def tool_read_file_range(ctx: ToolContext, args: dict) -> dict:
    raw_path = args.get("path")
    if not raw_path:
        return _error("'path' is required")
    try:
        start = int(args.get("start_line") or 1)
        end = int(args.get("end_line") or start + 40)
    except (TypeError, ValueError):
        return _error("'start_line' and 'end_line' must be integers")
    try:
        target = safe_join(ctx.workspace, str(raw_path))
    except PathSecurityError as exc:
        return _error(str(exc))
    if not target.exists() or not target.is_file():
        return _error(f"file not found in the workspace: {raw_path}")
    content = read_text(target)
    total = len(content.splitlines())
    start = max(1, start)
    end = min(total, max(start, end))
    if end - start > 400:
        end = start + 400
    return {
        "path": str(raw_path).replace("\\", "/"),
        "line_start": start,
        "line_end": end,
        "total_lines": total,
        "content": numbered_slice(content, start, end)[:MAX_READ_CHARS],
    }


async def tool_search_code(ctx: ToolContext, args: dict) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        return _error("'query' is required")
    matches = search_code(
        ctx.workspace,
        query,
        regex=bool(args.get("regex")),
        case_sensitive=bool(args.get("case_sensitive")),
        path_glob=(str(args.get("path_glob")).strip() or None) if args.get("path_glob") else None,
        limit=MAX_SEARCH_RESULTS,
    )
    return {
        "query": query,
        "match_count": len(matches),
        "matches": [match.as_dict() for match in matches],
    }


async def tool_find_symbol(ctx: ToolContext, args: dict) -> dict:
    name = str(args.get("name") or "").strip()
    if not name:
        return _error("'name' is required")
    symbols = find_symbol_definitions(ctx.workspace, name)
    return {
        "name": name,
        "definitions": [symbol.as_dict() for symbol in symbols[:20]],
    }


async def tool_inspect_project(ctx: ToolContext, args: dict) -> dict:
    metadata = ctx.metadata
    return {
        "language": metadata.language,
        "framework": metadata.framework,
        "entry_point": metadata.entry_point,
        "app_object": metadata.app_object,
        "test_framework": metadata.test_framework,
        "test_files": metadata.test_files,
        "dependencies": [
            {"name": dep.name, "specifier": dep.specifier} for dep in metadata.dependencies[:50]
        ],
        "routes": [
            {"method": r.method, "path": r.path, "file": r.file, "line": r.line, "function": r.function}
            for r in metadata.routes
        ],
        "source_files": metadata.source_files[:120],
        "file_tree": build_file_tree(ctx.workspace)[:80],
        "notes": metadata.notes,
    }


async def tool_inspect_tests(ctx: ToolContext, args: dict) -> dict:
    wanted = str(args.get("path") or "").strip()
    details = ctx.metadata.test_details
    if wanted:
        details = [d for d in details if d.path == wanted.replace("\\", "/")]
        if not details:
            return _error(f"no test file named {wanted} was found")
    payload = []
    for detail in details[:20]:
        entry = {
            "path": detail.path,
            "test_count": detail.test_count,
            "test_names": detail.test_names,
        }
        if wanted:
            target = ctx.workspace / detail.path
            if target.exists():
                content = read_text(target)
                entry["content"] = numbered_slice(content, 1, min(len(content.splitlines()), 300))[:MAX_READ_CHARS]
        payload.append(entry)
    return {"test_framework": ctx.metadata.test_framework, "files": payload}


async def tool_inspect_route(ctx: ToolContext, args: dict) -> dict:
    method = str(args.get("method") or "").strip().upper()
    path = str(args.get("path") or "").strip()
    if not path:
        return _error("'path' is required, e.g. '/users/{user_id}'")
    candidates = [
        route for route in ctx.metadata.routes
        if route.path == path and (not method or route.method.upper() == method)
    ]
    if not candidates:
        candidates = [route for route in ctx.metadata.routes if path in route.path]
    if not candidates:
        return _error(f"no route matching {method} {path} was discovered in this project")

    payload = []
    for route in candidates[:5]:
        entry = {
            "method": route.method,
            "path": route.path,
            "file": route.file,
            "line": route.line,
            "function": route.function,
            "status_codes": route.status_codes,
            "response_model": route.response_model,
            "parameters": route.parameters,
        }
        target = ctx.workspace / route.file
        if target.exists() and target.is_file() and route.line:
            content = read_text(target)
            symbol = enclosing_symbol(ctx.workspace, route.file, route.line + 1)
            start = route.line
            end = symbol.end_line if symbol else route.line + 30
            entry["source"] = numbered_slice(content, max(1, start - 2), end + 2)[:MAX_READ_CHARS]
        payload.append(entry)
    return {"routes": payload}


async def tool_get_stack_trace(ctx: ToolContext, args: dict) -> dict:
    if ctx.failure is None:
        return _error("there is no failure under investigation")
    failure = ctx.failure
    return {
        "error_type": failure.error_type,
        "message": failure.message,
        "file": failure.file,
        "line": failure.line,
        "function": failure.function,
        "test": failure.test,
        "endpoint": failure.endpoint,
        "status_code": failure.status_code,
        "traceback": failure.traceback[:12000],
        "frames": [
            {
                "file": frame.file, "line": frame.line, "function": frame.function,
                "code": frame.code, "in_project": frame.in_project,
            }
            for frame in failure.frames
        ],
    }


async def tool_get_openapi_schema(ctx: ToolContext, args: dict) -> dict:
    if ctx.openapi:
        return {"source": "runtime", "openapi": ctx.openapi}
    return {
        "source": "static",
        "note": (
            "The live /openapi.json was not captured for this run. These routes come "
            "from static analysis of the source."
        ),
        "routes": [
            {"method": r.method, "path": r.path, "file": r.file, "line": r.line}
            for r in ctx.metadata.routes
        ],
    }


# ---------------------------------------------------------------------------
# Execution tools (fixed commands only)
# ---------------------------------------------------------------------------


async def tool_run_targeted_test(ctx: ToolContext, args: dict) -> dict:
    raw = args.get("test") or args.get("selector") or args.get("node_id")
    if not raw:
        return _error("'test' is required, e.g. 'tests/test_users.py::test_get_user'")
    selectors: list[str] = []
    values = raw if isinstance(raw, list) else [raw]
    for value in values[:5]:
        try:
            selectors.append(validate_test_selector(str(value)))
        except ExecutionSecurityError as exc:
            return _error(str(exc))
    result = await run_tests(ctx.sandbox, ctx.workspace, selectors=selectors)
    if ctx.on_test_run is not None:
        await ctx.on_test_run(result)
    return _test_payload(result, selectors)


async def tool_run_full_tests(ctx: ToolContext, args: dict) -> dict:
    result = await run_tests(ctx.sandbox, ctx.workspace)
    if ctx.on_test_run is not None:
        await ctx.on_test_run(result)
    return _test_payload(result, None)


def _test_payload(result: TestRunResult, selectors: list[str] | None) -> dict:
    return {
        "selectors": selectors or ["<all tests>"],
        "exit_code": result.exit_code,
        "passed": result.passed,
        "failed": result.failed,
        "errors": result.errors,
        "total": result.total,
        "all_passed": result.all_passed,
        "duration_ms": result.duration_ms,
        "timed_out": result.timed_out,
        "collection_error": (result.collection_error or "")[:1200] or None,
        "stdout_tail": result.stdout[-8000:],
        "failing_tests": [c.node_id for c in result.cases if c.outcome in {"failed", "error"}],
        "runner": result.runner,
    }


async def tool_run_api_endpoint(ctx: ToolContext, args: dict) -> dict:
    """Start the API in the sandbox and call ONE endpoint."""
    from ..execution.api_runner import run_api_probe

    method = str(args.get("method") or "GET").strip().upper()
    path = str(args.get("path") or "").strip()
    if not path:
        return _error("'path' is required")
    if method not in {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}:
        return _error(f"unsupported HTTP method: {method}")

    signature = f"{method} {path}"
    result = await run_api_probe(
        ctx.sandbox,
        ctx.workspace,
        ctx.metadata,
        include_write_methods=method not in {"GET", "HEAD", "OPTIONS"},
        only=[signature],
    )
    if not result.started:
        return {
            "started": False,
            "startup_error": (result.startup_error or "")[:6000],
            "note": "the API did not start, so the endpoint could not be called",
        }
    probes = [
        {
            "method": probe.method,
            "path": probe.path,
            "concrete_url": probe.url,
            "status_code": probe.status_code,
            "latency_ms": probe.latency_ms,
            "response": probe.response_snippet[:3000],
            "error": probe.error,
        }
        for probe in result.probes
    ]
    if not probes:
        return {
            "started": True,
            "note": f"no discovered route matched {signature}",
            "available_routes": [r.signature for r in ctx.metadata.routes][:40],
        }
    return {
        "started": True,
        "requested": signature,
        "concrete_path": concretize_path(path),
        "probes": probes,
        "server_log_tail": (result.startup_stdout + result.startup_stderr)[-6000:],
    }


# ---------------------------------------------------------------------------
# Patch tools
# ---------------------------------------------------------------------------


async def tool_validate_patch(ctx: ToolContext, args: dict) -> dict:
    """Dry-run a candidate patch. Writes nothing.

    Exposed to the model so it can check its anchors before proposing a fix.
    """
    from ..models.patch import PatchProposal
    from ..patches.patch_parser import PatchParseError, edits_from_payload, new_patch_id
    from ..patches.patch_validator import validate_patch

    payload = args
    if isinstance(args.get("patch"), dict):
        payload = args["patch"]
    elif isinstance(args.get("patch"), str):
        try:
            payload = json.loads(args["patch"])
        except json.JSONDecodeError as exc:
            return _error(f"'patch' was not valid JSON: {exc}")
    try:
        edits = edits_from_payload(payload)
    except PatchParseError as exc:
        return _error(str(exc))

    proposal = PatchProposal(
        id=new_patch_id(),
        project_id="dry-run",
        edits=edits,
        title=str(payload.get("title") or "dry run"),
    )
    validation = validate_patch(ctx.workspace, proposal, ctx.settings)
    return {
        "valid": validation.valid,
        "issues": [
            {"severity": i.severity, "code": i.code, "message": i.message, "path": i.path}
            for i in validation.issues
        ],
        "files_touched": validation.files_touched,
        "lines_added": validation.lines_added,
        "lines_removed": validation.lines_removed,
        "diff": validation.diff[:8000],
        "note": "This was a dry run. Nothing was written to disk.",
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ToolImpl = Callable[[ToolContext, dict], Awaitable[dict]]

READ_ONLY_TOOLS: dict[str, ToolImpl] = {
    "list_files": tool_list_files,
    "read_file": tool_read_file,
    "read_file_range": tool_read_file_range,
    "search_code": tool_search_code,
    "find_symbol": tool_find_symbol,
    "inspect_project": tool_inspect_project,
    "inspect_tests": tool_inspect_tests,
    "inspect_route": tool_inspect_route,
    "get_stack_trace": tool_get_stack_trace,
    "get_openapi_schema": tool_get_openapi_schema,
}

EXECUTION_TOOLS: dict[str, ToolImpl] = {
    "run_targeted_test": tool_run_targeted_test,
    "run_full_tests": tool_run_full_tests,
    "run_api_endpoint": tool_run_api_endpoint,
}

PATCH_TOOLS: dict[str, ToolImpl] = {
    "validate_patch": tool_validate_patch,
}

ALL_TOOLS: dict[str, ToolImpl] = {**READ_ONLY_TOOLS, **EXECUTION_TOOLS, **PATCH_TOOLS}


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    """Responses-API function tool definition (flat shape, not nested in `function`)."""
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOL_SCHEMAS: list[dict] = [
    _schema(
        "inspect_project",
        "Get the project's language, framework, entry point, routes, dependencies, test files and file tree.",
        {},
        [],
    ),
    _schema(
        "get_stack_trace",
        "Get the full normalised stack trace and frames for the failure under investigation.",
        {},
        [],
    ),
    _schema(
        "list_files",
        "List files in the project workspace.",
        {
            "directory": {"type": "string", "description": "Project-relative directory, or '' for the root."},
            "pattern": {"type": "string", "description": "Case-insensitive substring filter on the path, or ''."},
        },
        ["directory", "pattern"],
    ),
    _schema(
        "read_file",
        "Read a file from the workspace with line numbers.",
        {"path": {"type": "string", "description": "Project-relative path, e.g. 'main.py'."}},
        ["path"],
    ),
    _schema(
        "read_file_range",
        "Read a specific line range of a file. Use this around the line in the stack trace.",
        {
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        ["path", "start_line", "end_line"],
    ),
    _schema(
        "search_code",
        "Search the source for a literal string or regex. Use it to find where a symbol or key is defined and used.",
        {
            "query": {"type": "string"},
            "regex": {"type": "boolean", "description": "Treat the query as a regular expression."},
            "path_glob": {"type": "string", "description": "Optional glob filter such as '*.py', or ''."},
        },
        ["query", "regex", "path_glob"],
    ),
    _schema(
        "find_symbol",
        "Find every definition of a function or class by name.",
        {"name": {"type": "string"}},
        ["name"],
    ),
    _schema(
        "inspect_tests",
        "List the project's tests, or read one test file in full.",
        {"path": {"type": "string", "description": "A test file path, or '' to list them all."}},
        ["path"],
    ),
    _schema(
        "inspect_route",
        "Inspect a discovered API route and read its handler source.",
        {
            "method": {"type": "string", "description": "HTTP method, or '' for any."},
            "path": {"type": "string", "description": "Route path such as '/users/{user_id}'."},
        },
        ["method", "path"],
    ),
    _schema(
        "get_openapi_schema",
        "Get the API contract: the live /openapi.json if it was captured, otherwise the statically discovered routes.",
        {},
        [],
    ),
    _schema(
        "run_targeted_test",
        "Run one or more specific tests by pytest node id and return the real result.",
        {
            "test": {
                "type": "array",
                "items": {"type": "string"},
                "description": "pytest node ids, e.g. ['tests/test_users.py::test_get_user'].",
            }
        },
        ["test"],
    ),
    _schema(
        "run_full_tests",
        "Run the project's entire test suite and return the real result.",
        {},
        [],
    ),
    _schema(
        "run_api_endpoint",
        "Start the API in the sandbox and call one endpoint, returning status, body and the server log.",
        {
            "method": {"type": "string"},
            "path": {"type": "string", "description": "Route path as declared, e.g. '/users/{user_id}'."},
        },
        ["method", "path"],
    ),
    _schema(
        "validate_patch",
        (
            "Dry-run a candidate patch against the real files: checks that each 'old' anchor "
            "appears exactly once, that the result parses, and reports the diff. Writes nothing. "
            "Use this before proposing a fix."
        ),
        {
            "edits": {
                "type": "array",
                "description": "The candidate edits.",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "operation": {"type": "string", "enum": ["replace", "insert_after", "create_file"]},
                        "old": {"type": "string"},
                        "new": {"type": "string"},
                    },
                    "required": ["path", "operation", "old", "new"],
                    "additionalProperties": False,
                },
            }
        },
        ["edits"],
    ),
]

# Tool names the model is allowed to see during investigation.
INVESTIGATION_TOOL_NAMES = {schema["name"] for schema in TOOL_SCHEMAS}


def investigation_tool_schemas(*, allow_execution: bool = True) -> list[dict]:
    if allow_execution:
        return TOOL_SCHEMAS
    blocked = set(EXECUTION_TOOLS)
    return [schema for schema in TOOL_SCHEMAS if schema["name"] not in blocked]


def summarize_tool_result(name: str, output: dict) -> str:
    """One-line summary for the activity feed and the investigation report."""
    if output.get("error"):
        return f"error: {output['error']}"[:200]
    if name in {"read_file", "read_file_range"}:
        return f"read {output.get('path')} (lines {output.get('line_start', 1)}-{output.get('line_end', output.get('total_lines', '?'))})"
    if name == "search_code":
        return f"{output.get('match_count', 0)} matches for {output.get('query')!r}"
    if name == "find_symbol":
        return f"{len(output.get('definitions', []))} definition(s) of {output.get('name')}"
    if name == "list_files":
        return f"{output.get('count', 0)} files in {output.get('directory')}"
    if name == "inspect_project":
        return f"{output.get('framework')} project, {len(output.get('routes', []))} routes"
    if name == "inspect_tests":
        return f"{len(output.get('files', []))} test file(s)"
    if name == "inspect_route":
        routes = output.get("routes", [])
        return f"inspected {routes[0]['method']} {routes[0]['path']}" if routes else "no route matched"
    if name == "get_stack_trace":
        return f"{output.get('error_type')}: {str(output.get('message'))[:80]}"
    if name == "get_openapi_schema":
        return f"contract from {output.get('source')}"
    if name in {"run_targeted_test", "run_full_tests"}:
        return (
            f"{output.get('passed', 0)} passed / {output.get('failed', 0)} failed "
            f"(exit {output.get('exit_code')})"
        )
    if name == "run_api_endpoint":
        probes = output.get("probes") or []
        if probes:
            return f"{probes[0]['method']} {probes[0]['path']} -> {probes[0]['status_code']}"
        return "endpoint not called"
    if name == "validate_patch":
        return "patch dry-run: valid" if output.get("valid") else "patch dry-run: invalid"
    return "ok"


async def execute_tool(ctx: ToolContext, name: str, arguments: dict) -> dict:
    """Dispatch a model tool request to its backend implementation."""
    impl = ALL_TOOLS.get(name)
    if impl is None:
        return _error(
            f"unknown tool {name!r}. Available tools: {', '.join(sorted(ALL_TOOLS))}"
        )
    if not isinstance(arguments, dict):
        return _error("tool arguments must be a JSON object")
    logger.info("tool call: %s(%s)", name, json.dumps(arguments, default=str)[:200])
    try:
        return await impl(ctx, arguments)
    except (PathSecurityError, ExecutionSecurityError) as exc:
        return _error(f"blocked by security policy: {exc}")
    except Exception as exc:  # noqa: BLE001 - a tool failure must not kill the loop
        logger.exception("tool %s raised", name)
        return _error(f"{type(exc).__name__}: {exc}")


def make_executor(ctx: ToolContext) -> Callable[[str, dict], Awaitable[dict]]:
    async def executor(name: str, arguments: dict) -> dict:
        return await execute_tool(ctx, name, arguments)

    return executor


def tool_context_summary(ctx: ToolContext) -> dict[str, Any]:
    return {
        "workspace_files": len(ctx.metadata.source_files),
        "routes": len(ctx.metadata.routes),
        "tests": len(ctx.metadata.test_files),
        "sandbox": ctx.sandbox.kind,
    }
