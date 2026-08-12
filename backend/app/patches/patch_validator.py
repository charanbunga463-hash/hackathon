"""Validate a patch before a single byte is written.

The checks, in order:

  1. Path safety     — inside the workspace, not protected, not a symlink.
  2. File existence  — replace/insert require the file; create must not clobber.
  3. Anchor match    — `old` must appear EXACTLY ONCE. Zero means the model
                       hallucinated the code; more than one means the edit is
                       ambiguous. Both are hard failures.
  4. Blast radius    — file count, edit count and changed-line budget.
  5. Syntax          — the post-edit content of every .py file must compile.
  6. Danger scan     — refuse patches that introduce process/network/eval calls
                       that were not already in the file.

Only when all of these pass does the patch become APPLYable.
"""

from __future__ import annotations

import ast
import difflib
from pathlib import Path

from ..config.settings import Settings
from ..models.patch import (
    EditOperation,
    FileEdit,
    PatchProposal,
    PatchValidation,
    ValidationIssue,
)
from ..security.path_security import PathSecurityError, assert_editable
from ..utils.filesystem import read_text

# Constructs a repair patch has no business introducing.
DANGEROUS_PATTERNS = [
    ("os.system", "shell execution"),
    ("subprocess.", "subprocess execution"),
    ("eval(", "dynamic evaluation"),
    ("exec(", "dynamic execution"),
    ("__import__(", "dynamic import"),
    ("pickle.loads", "unsafe deserialisation"),
    ("shutil.rmtree", "recursive delete"),
    ("os.remove", "file deletion"),
    ("os.unlink", "file deletion"),
    ("socket.socket", "raw socket"),
    ("requests.post", "outbound network call"),
    ("httpx.post", "outbound network call"),
    ("urllib.request.urlopen", "outbound network call"),
    ("OPENAI_API_KEY", "credential reference"),
]


def compute_new_content(original: str, edit: FileEdit) -> str:
    """Apply one edit to in-memory content. Pure; touches no disk."""
    if edit.operation is EditOperation.CREATE_FILE:
        return edit.new
    if edit.operation is EditOperation.REPLACE:
        return original.replace(edit.old, edit.new, 1)
    if edit.operation is EditOperation.INSERT_AFTER:
        index = original.find(edit.old)
        if index == -1:
            return original
        insert_at = index + len(edit.old)
        separator = "" if edit.new.startswith("\n") else "\n"
        return original[:insert_at] + separator + edit.new + original[insert_at:]
    return original


def unified_diff(path: str, before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    return "".join(diff)


def build_diff(workspace: Path, patch: PatchProposal) -> tuple[str, dict[str, str]]:
    """Return (combined unified diff, {path: final content}) without writing."""
    pending: dict[str, str] = {}
    diffs: list[str] = []
    for edit in patch.edits:
        relative = edit.path.replace("\\", "/")
        if relative in pending:
            before = pending[relative]
        else:
            target = workspace / relative
            before = read_text(target) if target.exists() and target.is_file() else ""
        after = compute_new_content(before, edit)
        pending[relative] = after
    for relative, after in pending.items():
        target = workspace / relative
        before = read_text(target) if target.exists() and target.is_file() else ""
        if before != after:
            diffs.append(unified_diff(relative, before, after))
    return "".join(diffs), pending


def validate_patch(
    workspace: Path, patch: PatchProposal, settings: Settings
) -> PatchValidation:
    issues: list[ValidationIssue] = []
    files_touched: list[str] = []
    syntax_checked: list[str] = []

    def error(code: str, message: str, path: str | None = None) -> None:
        issues.append(ValidationIssue(severity="error", code=code, message=message, path=path))

    def warn(code: str, message: str, path: str | None = None) -> None:
        issues.append(ValidationIssue(severity="warning", code=code, message=message, path=path))

    # ---------------------------------------------------------- structure --
    if not patch.edits:
        error("empty_patch", "the patch contains no edits")
        return PatchValidation(valid=False, issues=issues)

    if len(patch.edits) > settings.max_patch_edits:
        error(
            "too_many_edits",
            f"patch has {len(patch.edits)} edits, above the configured maximum of "
            f"{settings.max_patch_edits}",
        )

    distinct_paths = {edit.path.replace('\\', '/') for edit in patch.edits}
    if len(distinct_paths) > settings.max_patch_files:
        error(
            "too_many_files",
            f"patch touches {len(distinct_paths)} files, above the configured maximum of "
            f"{settings.max_patch_files}; a root-cause fix should be minimal",
        )

    # ------------------------------------------------ per-edit validation --
    pending: dict[str, str] = {}
    for index, edit in enumerate(patch.edits, start=1):
        relative = edit.path.replace("\\", "/")
        try:
            target = assert_editable(workspace, relative)
        except PathSecurityError as exc:
            error("unsafe_path", str(exc), relative)
            continue

        exists = target.exists() and target.is_file()
        if edit.operation is EditOperation.CREATE_FILE:
            if exists:
                error(
                    "file_exists",
                    f"edit #{index} wants to create {relative} but it already exists",
                    relative,
                )
                continue
            current = ""
        else:
            if relative in pending:
                current = pending[relative]
            elif not exists:
                error(
                    "missing_file",
                    f"edit #{index} targets {relative}, which does not exist in the workspace",
                    relative,
                )
                continue
            else:
                current = read_text(target)

            occurrences = current.count(edit.old)
            if occurrences == 0:
                error(
                    "anchor_not_found",
                    f"edit #{index}: the 'old' text was not found in {relative}. "
                    "The proposed change does not match the real file, so it was not applied.",
                    relative,
                )
                continue
            if occurrences > 1:
                error(
                    "anchor_ambiguous",
                    f"edit #{index}: the 'old' text appears {occurrences} times in {relative}. "
                    "The anchor must be unique so the edit lands in exactly one place.",
                    relative,
                )
                continue

        after = compute_new_content(current, edit)
        if after == current and edit.operation is not EditOperation.CREATE_FILE:
            warn("no_change", f"edit #{index} on {relative} produced no change", relative)
        pending[relative] = after
        if relative not in files_touched:
            files_touched.append(relative)

    if [issue for issue in issues if issue.severity == "error"]:
        diff, _ = _safe_diff(workspace, pending)
        return PatchValidation(valid=False, issues=issues, files_touched=files_touched, diff=diff)

    # -------------------------------------------------------- diff budget --
    diff, _ = _safe_diff(workspace, pending)
    added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
    if added + removed > settings.max_patch_lines_changed:
        error(
            "patch_too_large",
            f"patch changes {added + removed} lines, above the configured maximum of "
            f"{settings.max_patch_lines_changed}. Minimal fixes only.",
        )

    # ------------------------------------------------------------ syntax ---
    for relative, content in pending.items():
        if not relative.endswith(".py"):
            continue
        try:
            ast.parse(content, filename=relative)
            syntax_checked.append(relative)
        except SyntaxError as exc:
            error(
                "syntax_error",
                f"the patched version of {relative} is not valid Python: "
                f"{exc.msg} at line {exc.lineno}",
                relative,
            )

    # ------------------------------------------------------------ danger ---
    for relative, content in pending.items():
        target = workspace / relative
        original = read_text(target) if target.exists() and target.is_file() else ""
        for needle, label in DANGEROUS_PATTERNS:
            if content.count(needle) > original.count(needle):
                error(
                    "dangerous_construct",
                    f"the patch introduces {label} (`{needle}`) into {relative}, "
                    "which a bug fix should not need",
                    relative,
                )

    valid = not [issue for issue in issues if issue.severity == "error"]
    return PatchValidation(
        valid=valid,
        issues=issues,
        files_touched=files_touched,
        lines_added=added,
        lines_removed=removed,
        syntax_checked=syntax_checked,
        diff=diff,
    )


def _safe_diff(workspace: Path, pending: dict[str, str]) -> tuple[str, dict[str, str]]:
    diffs: list[str] = []
    for relative, after in pending.items():
        target = workspace / relative
        before = read_text(target) if target.exists() and target.is_file() else ""
        if before != after:
            diffs.append(unified_diff(relative, before, after))
    return "".join(diffs), pending
