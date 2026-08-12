"""Turn raw runner output into normalised failures.

This is the bridge between "a process printed some bytes" and the
`NormalizedFailure` records the agent reasons over. It never guesses: every
field it fills in comes from text actually present in the output.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..models.execution import EndpointProbeResult, NormalizedFailure, Severity
from .stacktrace_parser import (
    parse_traceback,
    severity_for,
    split_pytest_failures,
)

LOG_LEVEL_LINE = re.compile(
    r"^(?P<ts>[\d\-:\.T ]+)?\s*[\|\[]?\s*(?P<level>ERROR|CRITICAL|WARNING|EXCEPTION)\b[\]\|]?\s*(?P<body>.*)$",
    re.IGNORECASE,
)
HTTP_ACCESS_LINE = re.compile(
    r'"(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) (?P<path>[^\s"]+)[^"]*"\s+(?P<status>\d{3})'
)
NODE_ID = re.compile(r"^(?P<file>[^\s:]+\.py)::(?P<rest>.+)$")

FAILURE_STATUS_CODES = {400, 401, 403, 404, 405, 409, 415, 422, 429, 500, 501, 502, 503, 504}
SERVER_ERROR_CODES = {500, 501, 502, 503, 504}


TRACEBACK_LIMIT = 12000


def failure_id(*parts: str) -> str:
    digest = hashlib.sha256("::".join(p or "" for p in parts).encode("utf-8")).hexdigest()
    return f"fail_{digest[:12]}"


def clip_traceback(text: str, limit: int = TRACEBACK_LIMIT) -> str:
    """Clip a long traceback while keeping BOTH ends.

    The tail carries the actual exception and the raising frame, which is the
    highest-value part; a naive `text[:limit]` throws exactly that away on the
    deep tracebacks FastAPI's test client produces.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = limit // 4
    tail = limit - head
    return f"{text[:head]}\n\n...[{len(text) - limit} characters of middle frames omitted]...\n\n{text[-tail:]}"


def normalize_test_failure(
    node_id: str,
    block: str,
    *,
    project_root: Path | None = None,
    detail: str = "",
) -> NormalizedFailure:
    """Build a NormalizedFailure from one pytest failure block."""
    parsed = parse_traceback(block, project_root)
    culprit = parsed.culprit()

    error_type = parsed.error_type
    message = parsed.message
    if error_type == "UnknownError" and detail:
        # Fall back to the short-summary detail: "KeyError: 'username'".
        if ":" in detail:
            head, _, tail = detail.partition(":")
            if head.strip().endswith(("Error", "Exception", "Failure")):
                error_type, message = head.strip(), tail.strip()
        if error_type == "UnknownError" and detail.startswith("assert"):
            error_type, message = "AssertionError", detail

    # Prefer a frame in application code over one inside the test itself: the
    # test file is where the failure surfaced, the app file is where it lives.
    app_frames = [f for f in parsed.project_frames if not _is_test_path(f.file)]
    target = app_frames[-1] if app_frames else culprit

    return NormalizedFailure(
        id=failure_id(node_id, error_type, message, target.file if target else ""),
        error_type=error_type,
        message=message,
        file=target.file if target else None,
        line=target.line if target else None,
        function=target.function if target else None,
        test=node_id,
        severity=severity_for(error_type),
        traceback=clip_traceback(block),
        frames=parsed.frames,
        source="pytest",
        raw_output=clip_traceback(block),
    )


def _is_test_path(path: str | None) -> bool:
    if not path:
        return False
    normalized = path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{normalized}"


def failures_from_pytest_output(
    stdout: str,
    stderr: str,
    *,
    project_root: Path | None = None,
    short_summary: list[dict] | None = None,
) -> list[NormalizedFailure]:
    """Extract every distinct failure from a pytest run."""
    details = {entry["node_id"]: entry.get("detail", "") for entry in (short_summary or [])}
    blocks = split_pytest_failures(stdout)
    failures: list[NormalizedFailure] = []
    seen: set[str] = set()

    for name, block in blocks:
        node_id = _resolve_node_id(name, list(details))
        failure = normalize_test_failure(
            node_id, block, project_root=project_root, detail=details.get(node_id, "")
        )
        if failure.id in seen:
            continue
        seen.add(failure.id)
        failures.append(failure)

    if failures:
        return failures

    # No FAILURES section (collection error, internal error, hard crash).
    combined = f"{stdout}\n{stderr}".strip()
    if not combined:
        return []
    parsed = parse_traceback(combined, project_root)
    if parsed.error_type == "UnknownError" and not short_summary:
        return []
    culprit = parsed.culprit()
    for entry in short_summary or []:
        node_id = entry["node_id"]
        failures.append(
            normalize_test_failure(
                node_id, combined, project_root=project_root, detail=entry.get("detail", "")
            )
        )
    if failures:
        return failures
    return [
        NormalizedFailure(
            id=failure_id("collection", parsed.error_type, parsed.message),
            error_type=parsed.error_type,
            message=parsed.message,
            file=culprit.file if culprit else None,
            line=culprit.line if culprit else None,
            function=culprit.function if culprit else None,
            test=None,
            severity=severity_for(parsed.error_type),
            traceback=clip_traceback(combined),
            frames=parsed.frames,
            source="collection",
            raw_output=clip_traceback(combined),
        )
    ]


def _resolve_node_id(header_name: str, known_nodes: list[str]) -> str:
    """pytest headers use `test_users.test_get_user`; map back to a node id."""
    if "::" in header_name:
        return header_name
    for node in known_nodes:
        tail = node.split("::")[-1]
        if header_name.endswith(tail) or tail == header_name.rsplit(".", 1)[-1]:
            return node
    return header_name


def failure_from_probe(
    probe: EndpointProbeResult,
    *,
    server_log: str = "",
    project_root: Path | None = None,
) -> NormalizedFailure | None:
    """Turn a bad HTTP response into a normalised failure, mining the server log."""
    if probe.error is None and (probe.status_code is None or probe.status_code not in FAILURE_STATUS_CODES):
        return None

    traceback_text = ""
    if probe.status_code in SERVER_ERROR_CODES or probe.error:
        traceback_text = extract_last_traceback(server_log)

    parsed = parse_traceback(traceback_text or probe.response_snippet, project_root)
    culprit = None
    app_frames = [f for f in parsed.project_frames if not _is_test_path(f.file)]
    if app_frames:
        culprit = app_frames[-1]
    elif parsed.frames:
        culprit = parsed.frames[-1]

    if probe.error and parsed.error_type == "UnknownError":
        error_type = "ConnectionError"
        message = probe.error
        severity = Severity.CRITICAL
    elif parsed.error_type != "UnknownError":
        error_type = parsed.error_type
        message = parsed.message
        severity = severity_for(error_type)
    else:
        error_type = f"HTTP{probe.status_code}"
        message = (probe.response_snippet or "").strip()[:400] or f"unexpected status {probe.status_code}"
        severity = Severity.HIGH if (probe.status_code or 0) >= 500 else Severity.MEDIUM

    return NormalizedFailure(
        id=failure_id("probe", probe.method, probe.path, error_type, message),
        error_type=error_type,
        message=message,
        file=culprit.file if culprit else None,
        line=culprit.line if culprit else None,
        function=culprit.function if culprit else None,
        endpoint=f"{probe.method} {probe.path}",
        status_code=probe.status_code,
        severity=severity,
        traceback=traceback_text[:12000],
        frames=parsed.frames,
        source="api_probe",
        raw_output=(probe.response_snippet or "")[:4000],
    )


def extract_last_traceback(log: str) -> str:
    """Pull the final `Traceback (most recent call last):` block out of a log."""
    if not log:
        return ""
    marker = "Traceback (most recent call last):"
    index = log.rfind(marker)
    if index == -1:
        return ""
    tail = log[index:]
    # Stop at the next access-log line, which follows the traceback.
    stop = re.search(r"\n(?:INFO|WARNING|DEBUG)\s*:", tail)
    return tail[: stop.start()] if stop else tail[:12000]


def extract_error_lines(log: str, limit: int = 40) -> list[str]:
    """Collect ERROR/CRITICAL log lines for the evidence panel."""
    hits: list[str] = []
    for line in (log or "").splitlines():
        if LOG_LEVEL_LINE.match(line.strip()) and len(line.strip()) > 8:
            hits.append(line.strip()[:400])
        if len(hits) >= limit:
            break
    return hits


def extract_access_log(log: str, limit: int = 60) -> list[dict]:
    entries: list[dict] = []
    for line in (log or "").splitlines():
        match = HTTP_ACCESS_LINE.search(line)
        if match:
            entries.append(
                {
                    "method": match.group("method"),
                    "path": match.group("path"),
                    "status": int(match.group("status")),
                }
            )
        if len(entries) >= limit:
            break
    return entries
