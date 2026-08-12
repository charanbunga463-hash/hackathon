"""Turn model output into a structured `PatchProposal`.

The model is asked for structured JSON edits, but real deployments see
malformed output, fenced code blocks, and occasionally a unified diff even when
one was not requested. This module accepts all three and normalises them into
anchored replacements, or fails loudly. It never `exec`s anything.
"""

from __future__ import annotations

import json
import re
import uuid

from ..models.patch import EditOperation, FileEdit, PatchProposal

FENCE = re.compile(r"^```[a-zA-Z0-9_+-]*\s*\n(?P<body>.*?)\n?```\s*$", re.S)
DIFF_HEADER = re.compile(r"^(?:---|\+\+\+)\s+(?:a/|b/)?(?P<path>.+?)\s*$")
HUNK_HEADER = re.compile(r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_len>\d+))?\s+\+(?P<new_start>\d+)(?:,(?P<new_len>\d+))?\s+@@")


class PatchParseError(ValueError):
    """Raised when model output cannot be turned into a patch."""


def new_patch_id() -> str:
    return f"patch_{uuid.uuid4().hex[:12]}"


def strip_fences(text: str) -> str:
    cleaned = (text or "").strip()
    match = FENCE.match(cleaned)
    if match:
        return match.group("body")
    return cleaned


def parse_json_object(text: str) -> dict:
    """Extract the first JSON object from possibly-noisy model output."""
    cleaned = strip_fences(text)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
        raise PatchParseError("expected a JSON object at the top level")
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        raise PatchParseError("no JSON object found in model output")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                fragment = cleaned[start : index + 1]
                try:
                    parsed = json.loads(fragment)
                except json.JSONDecodeError as exc:
                    raise PatchParseError(f"malformed JSON in model output: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise PatchParseError("expected a JSON object")
                return parsed
    raise PatchParseError("unbalanced JSON braces in model output")


def edits_from_payload(payload: dict) -> list[FileEdit]:
    raw_edits = payload.get("edits")
    if raw_edits is None:
        raise PatchParseError("patch payload has no 'edits' array")
    if not isinstance(raw_edits, list):
        raise PatchParseError("'edits' must be an array")
    if not raw_edits:
        raise PatchParseError("'edits' is empty; a patch must change something")

    edits: list[FileEdit] = []
    for index, raw in enumerate(raw_edits):
        if not isinstance(raw, dict):
            raise PatchParseError(f"edit #{index + 1} is not an object")
        path = raw.get("path") or raw.get("file")
        if not path:
            raise PatchParseError(f"edit #{index + 1} is missing 'path'")
        operation_raw = str(raw.get("operation") or "replace").lower().strip()
        aliases = {
            "replace": EditOperation.REPLACE,
            "edit": EditOperation.REPLACE,
            "modify": EditOperation.REPLACE,
            "insert_after": EditOperation.INSERT_AFTER,
            "insert": EditOperation.INSERT_AFTER,
            "create_file": EditOperation.CREATE_FILE,
            "create": EditOperation.CREATE_FILE,
            "new_file": EditOperation.CREATE_FILE,
        }
        operation = aliases.get(operation_raw)
        if operation is None:
            raise PatchParseError(
                f"edit #{index + 1} has unsupported operation {operation_raw!r}; "
                "expected replace, insert_after or create_file"
            )
        old = _as_text(raw.get("old") if "old" in raw else raw.get("before"))
        new = _as_text(raw.get("new") if "new" in raw else raw.get("after"))

        if operation is EditOperation.REPLACE and not old:
            raise PatchParseError(
                f"edit #{index + 1} for {path} is a replace but has no 'old' anchor text"
            )
        if operation is EditOperation.INSERT_AFTER and not old:
            raise PatchParseError(
                f"edit #{index + 1} for {path} is an insert_after but has no 'old' anchor text"
            )
        if operation is EditOperation.CREATE_FILE and not new:
            raise PatchParseError(f"edit #{index + 1} creates {path} with empty content")
        if operation is EditOperation.REPLACE and old == new:
            raise PatchParseError(f"edit #{index + 1} for {path} is a no-op (old == new)")

        line_hint = raw.get("line_hint") or raw.get("line")
        try:
            line_hint = int(line_hint) if line_hint is not None else None
        except (TypeError, ValueError):
            line_hint = None

        edits.append(
            FileEdit(
                path=str(path).strip(),
                operation=operation,
                old=old,
                new=new,
                line_hint=line_hint,
                reason=str(raw.get("reason") or raw.get("explanation") or "").strip(),
            )
        )
    return edits


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def build_proposal(
    payload: dict,
    *,
    project_id: str,
    failure_id: str | None,
    attempt: int,
    reasoning_engine: str,
) -> PatchProposal:
    edits = edits_from_payload(payload)
    confidence = payload.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    tests = payload.get("tests_to_run") or []
    if isinstance(tests, str):
        tests = [tests]
    return PatchProposal(
        id=new_patch_id(),
        project_id=project_id,
        failure_id=failure_id,
        attempt=attempt,
        title=str(payload.get("title") or "Proposed fix").strip()[:200],
        explanation=str(payload.get("explanation") or payload.get("reason") or "").strip(),
        edits=edits,
        tests_to_run=[str(t) for t in tests if str(t).strip()][:10],
        risk=str(payload.get("risk") or "low").lower().strip(),
        confidence=confidence,
        reasoning_engine=reasoning_engine,
    )


def parse_unified_diff(diff_text: str) -> list[FileEdit]:
    """Fallback: convert a unified diff into anchored replacements.

    Only clean single-hunk-per-file diffs with context are supported; anything
    ambiguous raises so the caller can ask the model for structured output
    instead of guessing.
    """
    lines = strip_fences(diff_text).splitlines()
    edits: list[FileEdit] = []
    current_path: str | None = None
    old_lines: list[str] = []
    new_lines: list[str] = []
    line_hint: int | None = None
    in_hunk = False

    def flush() -> None:
        nonlocal old_lines, new_lines, in_hunk
        if current_path and in_hunk and (old_lines or new_lines):
            old_text = "\n".join(old_lines)
            new_text = "\n".join(new_lines)
            if old_text != new_text:
                edits.append(
                    FileEdit(
                        path=current_path,
                        operation=EditOperation.REPLACE,
                        old=old_text,
                        new=new_text,
                        line_hint=line_hint,
                        reason="converted from unified diff",
                    )
                )
        old_lines, new_lines = [], []
        in_hunk = False

    for line in lines:
        if line.startswith("--- "):
            flush()
            continue
        if line.startswith("+++ "):
            flush()
            header = DIFF_HEADER.match(line)
            if header:
                path = header.group("path").strip()
                current_path = None if path in {"/dev/null"} else path
            continue
        hunk = HUNK_HEADER.match(line)
        if hunk:
            flush()
            in_hunk = True
            line_hint = int(hunk.group("old_start"))
            continue
        if not in_hunk:
            continue
        if line.startswith("-"):
            old_lines.append(line[1:])
        elif line.startswith("+"):
            new_lines.append(line[1:])
        elif line.startswith(" ") or line == "":
            body = line[1:] if line.startswith(" ") else ""
            old_lines.append(body)
            new_lines.append(body)
        elif line.startswith("\\"):
            continue
        else:
            flush()

    flush()
    if not edits:
        raise PatchParseError("no applicable changes found in the diff")
    return edits
