"""Patch generation stage.

Produces a `PatchProposal`, validates it against the real files, and — when the
first attempt's anchors do not match — asks the model once more with the exact
validator errors, which is the failure mode that matters most in practice
(models reconstruct code from memory instead of copying it).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..ai.context_builder import as_prompt_json
from ..ai.openai_client import OpenAIClient, StructuredOutputError
from ..ai.schemas import AIPatchProposal, AIPatchReview
from ..config.settings import Settings
from ..models.diagnosis import DiagnosisResult, RepairPlan
from ..models.execution import NormalizedFailure
from ..models.patch import (
    EditOperation,
    FileEdit,
    PatchProposal,
    PatchStatus,
    PatchValidation,
)
from ..models.project import ProjectMetadata
from ..patches.patch_parser import new_patch_id
from ..patches.patch_validator import validate_patch
from ..utils.filesystem import numbered_slice, read_text
from ..utils.logging import get_logger
from .prompts import load_prompt

logger = get_logger(__name__)


def _diagnosis_payload(diagnosis: DiagnosisResult) -> dict:
    return {
        "summary": diagnosis.summary,
        "root_cause": diagnosis.root_cause,
        "confidence": diagnosis.confidence,
        "severity": diagnosis.severity.value,
        "affected_endpoint": diagnosis.affected_endpoint,
        "evidence": [
            {"kind": e.kind.value, "source": e.source, "line": e.line, "detail": e.detail, "excerpt": e.excerpt}
            for e in diagnosis.evidence
        ],
        "affected_files": [
            {"path": f.path, "line_start": f.line_start, "line_end": f.line_end, "reason": f.reason}
            for f in diagnosis.affected_files
        ],
    }


def _current_sources(workspace: Path, diagnosis: DiagnosisResult, failure: NormalizedFailure) -> list[dict]:
    """Exact current content of the files to be edited.

    The model must copy anchors from THIS text, so it is supplied verbatim (with
    line numbers, and an explicit warning that the numbers are not part of the file).
    """
    paths: list[str] = [entry.path for entry in diagnosis.affected_files]
    if failure.file and failure.file not in paths:
        paths.append(failure.file)
    sources: list[dict] = []
    for relative in dict.fromkeys(paths):
        target = workspace / relative
        if not target.exists() or not target.is_file():
            continue
        content = read_text(target)
        total = len(content.splitlines())
        sources.append(
            {
                "path": relative,
                "total_lines": total,
                "content_with_line_numbers": numbered_slice(content, 1, min(total, 400)),
                "note": (
                    "The 'NNN | ' prefix is display only. Anchor text must NOT include it."
                ),
            }
        )
    return sources


async def generate_with_ai(
    client: OpenAIClient,
    workspace: Path,
    metadata: ProjectMetadata,
    failure: NormalizedFailure,
    diagnosis: DiagnosisResult,
    plan: RepairPlan | None,
    settings: Settings,
    *,
    project_id: str,
    attempt: int,
    previous_attempts: list[dict] | None = None,
    retry_guidance: str = "",
) -> tuple[PatchProposal, PatchValidation]:
    """Generate + validate, with one anchor-correcting retry."""
    context: dict = {
        "diagnosis": _diagnosis_payload(diagnosis),
        "failure": {
            "error_type": failure.error_type,
            "message": failure.message,
            "file": failure.file,
            "line": failure.line,
            "test": failure.test,
            "endpoint": failure.endpoint,
            "traceback": failure.traceback[:4000],
        },
        "current_file_contents": _current_sources(workspace, diagnosis, failure),
        "project": {
            "framework": metadata.framework,
            "entry_point": metadata.entry_point,
            "test_files": metadata.test_files,
        },
        "constraints": {
            "max_files": settings.max_patch_files,
            "max_edits": settings.max_patch_edits,
            "max_lines_changed": settings.max_patch_lines_changed,
            "do_not_modify": metadata.test_files,
        },
    }
    if plan is not None:
        context["plan"] = plan.model_dump(mode="json")
    if previous_attempts:
        context["previous_failed_attempts"] = previous_attempts[-3:]
    if retry_guidance:
        context["retry_guidance"] = retry_guidance

    instructions = load_prompt("patch_generation")
    payload = await client.generate_patch(
        instructions=instructions, context=as_prompt_json(context)
    )
    patch = _to_proposal(payload, project_id=project_id, failure=failure, attempt=attempt)
    validation = validate_patch(workspace, patch, settings)

    if not validation.valid:
        errors = [f"- [{i.code}] {i.message}" for i in validation.errors]
        logger.info("patch %s failed validation, requesting a correction", patch.id)
        context["validation_failure"] = {
            "rejected_edits": [e.model_dump(mode="json") for e in patch.edits],
            "errors": errors,
            "instruction": (
                "Your previous patch was REJECTED before it was applied. The most common "
                "cause is an 'old' anchor that does not match the file byte-for-byte. "
                "Re-read current_file_contents above and copy the anchor text exactly, "
                "without the line-number prefix, choosing enough lines to make it unique."
            ),
        }
        try:
            payload = await client.generate_patch(
                instructions=instructions, context=as_prompt_json(context)
            )
        except StructuredOutputError:
            patch.status = PatchStatus.REJECTED
            return patch, validation
        retry_patch = _to_proposal(payload, project_id=project_id, failure=failure, attempt=attempt)
        retry_validation = validate_patch(workspace, retry_patch, settings)
        if retry_validation.valid:
            retry_patch.status = PatchStatus.VALIDATED
            retry_patch.diff = retry_validation.diff
            retry_patch.stats = {
                "lines_added": retry_validation.lines_added,
                "lines_removed": retry_validation.lines_removed,
                "files": len(retry_validation.files_touched),
                "corrected_after_rejection": True,
            }
            return retry_patch, retry_validation
        retry_patch.status = PatchStatus.REJECTED
        return retry_patch, retry_validation

    patch.status = PatchStatus.VALIDATED
    patch.diff = validation.diff
    patch.stats = {
        "lines_added": validation.lines_added,
        "lines_removed": validation.lines_removed,
        "files": len(validation.files_touched),
    }
    return patch, validation


def _to_proposal(
    payload: AIPatchProposal, *, project_id: str, failure: NormalizedFailure, attempt: int
) -> PatchProposal:
    edits = [
        FileEdit(
            path=edit.path.replace("\\", "/").lstrip("./"),
            operation=EditOperation(edit.operation),
            old=_strip_line_numbers(edit.old),
            new=_strip_line_numbers(edit.new),
            line_hint=edit.line_hint or None,
            reason=edit.reason,
        )
        for edit in payload.edits
    ]
    return PatchProposal(
        id=new_patch_id(),
        project_id=project_id,
        failure_id=failure.id,
        attempt=attempt,
        title=payload.title.strip()[:200] or "Proposed fix",
        explanation=payload.explanation.strip(),
        edits=edits,
        tests_to_run=[t for t in payload.tests_to_run if t.strip()][:10],
        risk=payload.risk,
        confidence=payload.confidence,
        reasoning_engine="openai",
    )


_LINE_PREFIX = re.compile(r"^\s*\d+\s*\|\s?", re.M)


def _strip_line_numbers(text: str) -> str:
    """Undo the `  15 | code` display format if the model copied it verbatim.

    Only applied when EVERY non-empty line carries the prefix, so real code
    containing a pipe character is left alone.
    """
    if not text:
        return text
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return text
    if all(_LINE_PREFIX.match(line) for line in lines):
        return _LINE_PREFIX.sub("", text)
    return text


async def review_with_ai(
    client: OpenAIClient,
    patch: PatchProposal,
    diagnosis: DiagnosisResult,
    validation: PatchValidation,
    metadata: ProjectMetadata,
) -> AIPatchReview | None:
    """Second-opinion review. Never blocks on failure — it is advisory."""
    context = {
        "diagnosis": _diagnosis_payload(diagnosis),
        "patch": {
            "title": patch.title,
            "explanation": patch.explanation,
            "risk": patch.risk,
            "confidence": patch.confidence,
            "edits": [e.model_dump(mode="json") for e in patch.edits],
        },
        "diff": validation.diff[:12000],
        "validation": {
            "files_touched": validation.files_touched,
            "lines_added": validation.lines_added,
            "lines_removed": validation.lines_removed,
            "warnings": [i.message for i in validation.warnings],
        },
        "test_files": metadata.test_files,
    }
    try:
        return await client.review_patch(
            instructions=load_prompt("patch_review"), context=as_prompt_json(context)
        )
    except Exception as exc:  # noqa: BLE001 - review is advisory
        logger.warning("patch review unavailable: %s", exc)
        return None


def touches_tests(patch: PatchProposal, metadata: ProjectMetadata) -> list[str]:
    test_files = {path.replace("\\", "/") for path in metadata.test_files}
    return [edit.path for edit in patch.edits if edit.path.replace("\\", "/") in test_files]
