"""Rank project files by relevance to a failure.

Context windows are finite and the agent should look at the right file first.
Scoring is deliberately transparent — every point is attributable to a rule, so
the investigation report can say *why* a file was read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..models.execution import NormalizedFailure
from ..models.project import ProjectMetadata
from ..utils.filesystem import read_text
from .code_search import extract_identifiers, extract_quoted_strings, search_code


@dataclass
class RankedFile:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)
    focus_line: int | None = None

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "score": round(self.score, 2),
            "reasons": self.reasons,
            "focus_line": self.focus_line,
        }


def rank_files(
    root: Path,
    failure: NormalizedFailure,
    metadata: ProjectMetadata,
    *,
    limit: int = 8,
) -> list[RankedFile]:
    scores: dict[str, RankedFile] = {}

    def bump(path: str, points: float, reason: str, line: int | None = None) -> None:
        if not path:
            return
        normalized = path.replace("\\", "/")
        entry = scores.get(normalized)
        if entry is None:
            entry = RankedFile(path=normalized, score=0.0)
            scores[normalized] = entry
        entry.score += points
        if reason not in entry.reasons:
            entry.reasons.append(reason)
        if line and entry.focus_line is None:
            entry.focus_line = line

    # 1. The frame the exception was raised in is the strongest signal there is.
    if failure.file:
        bump(failure.file, 12.0, f"stack trace points here (line {failure.line})", failure.line)

    # 2. Other project frames, weighted by depth.
    for depth, frame in enumerate(reversed([f for f in failure.frames if f.in_project])):
        bump(frame.file, max(1.0, 6.0 - depth), f"appears in stack trace at line {frame.line}", frame.line)

    # 3. The failing test file.
    if failure.test and "::" in failure.test:
        bump(failure.test.split("::")[0], 7.0, "this is the failing test")
    elif failure.test:
        bump(failure.test, 5.0, "referenced by the failing test id")

    # 4. The file declaring the failing endpoint.
    if failure.endpoint:
        for route in metadata.routes:
            if route.signature == failure.endpoint:
                bump(route.file, 10.0, f"declares {route.signature}", route.line)

    # 5. Files containing the quoted token from the error message
    #    (`KeyError: 'username'` -> search for "username").
    for token in extract_quoted_strings(failure.message)[:3]:
        if len(token) < 3:
            continue
        for match in search_code(root, token, limit=12):
            bump(match.path, 3.0, f"mentions {token!r}", match.line)

    # 6. Identifiers from the error message and the culprit source line.
    culprit_line = _culprit_source(root, failure)
    identifier_source = f"{failure.message} {culprit_line}"
    for identifier in extract_identifiers(identifier_source)[:4]:
        for match in search_code(root, identifier, limit=8):
            bump(match.path, 1.2, f"references `{identifier}`", match.line)

    # 7. The entry point is nearly always worth a look.
    if metadata.entry_point:
        bump(metadata.entry_point, 2.5, "application entry point")

    # Penalties keep vendored/generated files out of the context window.
    for entry in scores.values():
        lowered = entry.path.lower()
        if "/migrations/" in lowered or lowered.endswith(("__init__.py", ".lock")):
            entry.score -= 1.5
        if lowered.endswith((".md", ".txt", ".json")) and not lowered.endswith("openapi.json"):
            entry.score -= 2.0
        if not (root / entry.path).exists():
            entry.score -= 8.0
            entry.reasons.append("file not found in workspace")

    ranked = sorted(scores.values(), key=lambda item: -item.score)
    return [entry for entry in ranked if entry.score > 0][:limit]


def _culprit_source(root: Path, failure: NormalizedFailure) -> str:
    if not failure.file or not failure.line:
        return ""
    target = root / failure.file
    if not target.exists() or not target.is_file():
        return ""
    lines = read_text(target).splitlines()
    index = failure.line - 1
    if 0 <= index < len(lines):
        return lines[index]
    return ""


def relevant_tests(metadata: ProjectMetadata, failure: NormalizedFailure, limit: int = 5) -> list[str]:
    """Which tests should be run to check this specific failure?"""
    selected: list[str] = []
    if failure.test:
        selected.append(failure.test)
    endpoint_tokens: list[str] = []
    if failure.endpoint:
        path = failure.endpoint.split(" ", 1)[-1]
        endpoint_tokens = [token for token in path.strip("/").split("/") if token and "{" not in token]
    for detail in metadata.test_details:
        for name in detail.test_names:
            node = f"{detail.path}::{name.replace('::', '::')}"
            if node in selected:
                continue
            if endpoint_tokens and any(token in name.lower() for token in endpoint_tokens):
                selected.append(node)
            elif failure.function and failure.function.lower() in name.lower():
                selected.append(node)
        if len(selected) >= limit:
            break
    return selected[:limit]
