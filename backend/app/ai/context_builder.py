"""Build the context the model reasons over.

Context is assembled deterministically from real project artefacts. Nothing here
is invented: if a file is not in the workspace it does not appear in the context,
which is what makes the grounding check in the diagnostician meaningful.

Budgets are enforced so a large repository cannot blow the context window.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..analysis.code_search import enclosing_symbol
from ..analysis.relevance_ranker import RankedFile, rank_files
from ..models.execution import NormalizedFailure, TestRunResult
from ..models.project import ProjectMetadata
from ..utils.filesystem import numbered_slice, read_text

MAX_FILE_CHARS = 9000
MAX_SNIPPET_LINES = 90
MAX_TRACEBACK_CHARS = 6000
MAX_TEST_OUTPUT_CHARS = 6000
MAX_CONTEXT_FILES = 6


def summarize_metadata(metadata: ProjectMetadata | None) -> dict:
    if metadata is None:
        return {"analyzed": False}
    return {
        "language": metadata.language,
        "framework": metadata.framework,
        "entry_point": metadata.entry_point,
        "app_object": metadata.app_object,
        "test_framework": metadata.test_framework,
        "test_files": metadata.test_files[:20],
        "routes": [
            {
                "method": route.method,
                "path": route.path,
                "file": route.file,
                "line": route.line,
                "function": route.function,
                "status_codes": route.status_codes,
                "response_model": route.response_model,
            }
            for route in metadata.routes[:40]
        ],
        "dependencies": [dep.name for dep in metadata.dependencies[:40]],
        "source_files": metadata.source_files[:60],
        "notes": metadata.notes,
    }


def summarize_failure(failure: NormalizedFailure) -> dict:
    return {
        "id": failure.id,
        "error_type": failure.error_type,
        "message": failure.message,
        "file": failure.file,
        "line": failure.line,
        "function": failure.function,
        "test": failure.test,
        "endpoint": failure.endpoint,
        "status_code": failure.status_code,
        "severity": failure.severity.value,
        "source": failure.source,
        "traceback": failure.traceback[:MAX_TRACEBACK_CHARS],
        "frames": [
            {
                "file": frame.file,
                "line": frame.line,
                "function": frame.function,
                "code": frame.code,
                "in_project": frame.in_project,
            }
            for frame in failure.frames[-12:]
        ],
    }


def summarize_test_run(run: TestRunResult | None) -> dict:
    if run is None:
        return {"ran": False}
    return {
        "ran": True,
        "exit_code": run.exit_code,
        "passed": run.passed,
        "failed": run.failed,
        "errors": run.errors,
        "total": run.total,
        "duration_ms": run.duration_ms,
        "timed_out": run.timed_out,
        "collection_error": (run.collection_error or "")[:1500] or None,
        "stdout_tail": run.stdout[-MAX_TEST_OUTPUT_CHARS:],
        "stderr_tail": run.stderr[-2000:],
        "failing_tests": [c.node_id for c in run.cases if c.outcome in {"failed", "error"}][:20],
    }


def file_excerpt(
    workspace: Path,
    relative: str,
    *,
    focus_line: int | None = None,
    radius: int = 35,
) -> dict:
    """A numbered excerpt centred on the interesting line, or the file head."""
    target = workspace / relative
    if not target.exists() or not target.is_file():
        return {"path": relative, "found": False, "content": "", "note": "file not found in workspace"}
    content = read_text(target)
    total_lines = len(content.splitlines())
    if focus_line and total_lines > MAX_SNIPPET_LINES:
        start = max(1, focus_line - radius)
        end = min(total_lines, focus_line + radius)
        excerpt = numbered_slice(content, start, end)
        return {
            "path": relative,
            "found": True,
            "total_lines": total_lines,
            "line_start": start,
            "line_end": end,
            "content": excerpt[:MAX_FILE_CHARS],
            "truncated": end < total_lines or start > 1,
        }
    truncated = len(content) > MAX_FILE_CHARS
    excerpt = numbered_slice(content, 1, min(total_lines, 400))
    return {
        "path": relative,
        "found": True,
        "total_lines": total_lines,
        "line_start": 1,
        "line_end": min(total_lines, 400),
        "content": excerpt[:MAX_FILE_CHARS],
        "truncated": truncated or total_lines > 400,
    }


def build_failure_context(
    workspace: Path,
    metadata: ProjectMetadata,
    failure: NormalizedFailure,
    *,
    test_run: TestRunResult | None = None,
    openapi: dict | None = None,
    ranked: list[RankedFile] | None = None,
) -> dict:
    """The full investigation packet for one failure."""
    ranked = ranked if ranked is not None else rank_files(workspace, failure, metadata)
    files: list[dict] = []
    for entry in ranked[:MAX_CONTEXT_FILES]:
        excerpt = file_excerpt(workspace, entry.path, focus_line=entry.focus_line)
        excerpt["relevance"] = entry.reasons
        excerpt["relevance_score"] = round(entry.score, 2)
        files.append(excerpt)

    symbol = None
    if failure.file and failure.line:
        found = enclosing_symbol(workspace, failure.file, failure.line)
        if found:
            symbol = found.as_dict()

    contract = None
    if openapi:
        contract = {
            "title": (openapi.get("info") or {}).get("title"),
            "paths": _trim_openapi_paths(openapi, failure.endpoint),
        }
    elif failure.endpoint:
        route = next(
            (r for r in metadata.routes if r.signature == failure.endpoint), None
        )
        if route:
            contract = {
                "declared_route": {
                    "method": route.method,
                    "path": route.path,
                    "file": route.file,
                    "line": route.line,
                    "response_model": route.response_model,
                    "status_codes": route.status_codes,
                }
            }

    return {
        "project": summarize_metadata(metadata),
        "failure": summarize_failure(failure),
        "test_run": summarize_test_run(test_run),
        "candidate_files": files,
        "failing_symbol": symbol,
        "api_contract": contract,
        "workspace_files": metadata.source_files[:80],
    }


def _trim_openapi_paths(openapi: dict, endpoint: str | None) -> dict:
    paths = openapi.get("paths") or {}
    if not endpoint:
        return {key: value for key, value in list(paths.items())[:12]}
    wanted = endpoint.split(" ", 1)[-1]
    if wanted in paths:
        return {wanted: paths[wanted]}
    return {key: value for key, value in list(paths.items())[:12]}


def build_retry_context(
    previous_attempts: list[dict],
    *,
    limit: int = 3,
) -> dict:
    """What has already been tried, so the model does not repeat itself."""
    return {
        "previous_attempts": previous_attempts[-limit:],
        "instruction": (
            "These approaches have already been applied and verified against the real "
            "test suite. They did NOT fix the failure. Do not propose the same change again."
        ),
    }


def as_prompt_json(payload: dict, *, max_chars: int = 90_000) -> str:
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n...[context truncated to fit the model context window]..."
