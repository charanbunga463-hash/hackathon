"""Diagnosis stage — produce a root cause, and prove its evidence is real.

The grounding check is the heart of this module. A model can produce a fluent,
plausible diagnosis citing `app/services/users.py:212` in a project that has no
such file. Every evidence item is therefore checked against the workspace before
the diagnosis is shown to anyone:

  * a file source must exist
  * a line number must be within that file
  * a pytest node id must belong to a discovered test file
  * an endpoint must be a discovered route

Items that fail are removed and listed in `ungrounded_evidence`, and the
diagnosis is marked `grounded=False`. The UI shows that state explicitly rather
than hiding it.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..ai.schemas import AIDiagnosisResult
from ..models.diagnosis import (
    AffectedFile,
    DiagnosisResult,
    EvidenceItem,
    EvidenceKind,
    Hypothesis,
)
from ..models.execution import NormalizedFailure, Severity
from ..models.project import ProjectMetadata
from ..utils.filesystem import read_text
from ..utils.logging import get_logger

logger = get_logger(__name__)

NODE_ID = re.compile(r"^(?P<file>[^\s:]+\.py)::")
ENDPOINT = re.compile(r"^(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(?P<path>/\S*)$", re.I)


def _source_is_real(
    workspace: Path, metadata: ProjectMetadata, source: str, line: int | None
) -> tuple[bool, str]:
    """Can this evidence source be resolved to something in the project?"""
    cleaned = (source or "").strip()
    if not cleaned:
        return False, "empty source"

    endpoint = ENDPOINT.match(cleaned)
    if endpoint:
        signature = f"{endpoint.group('method').upper()} {endpoint.group('path')}"
        known = {route.signature for route in metadata.routes}
        if signature in known:
            return True, ""
        # Tolerate a concrete path where a templated route was declared.
        for route in metadata.routes:
            pattern = re.sub(r"\{[^}]+\}", r"[^/]+", route.path)
            if route.method.upper() == endpoint.group("method").upper() and re.fullmatch(
                pattern, endpoint.group("path")
            ):
                return True, ""
        return False, f"no route matching {signature} was discovered"

    node = NODE_ID.match(cleaned)
    candidate = node.group("file") if node else cleaned.split(":")[0]
    candidate = candidate.replace("\\", "/").lstrip("./")
    target = workspace / candidate
    if not target.exists() or not target.is_file():
        return False, f"{candidate} does not exist in the workspace"

    if line and line > 0:
        total = len(read_text(target).splitlines())
        if line > total:
            return False, f"{candidate} has {total} lines; line {line} does not exist"
    return True, ""


def ground_evidence(
    workspace: Path, metadata: ProjectMetadata, items: list[EvidenceItem]
) -> tuple[list[EvidenceItem], list[str]]:
    kept: list[EvidenceItem] = []
    rejected: list[str] = []
    for item in items:
        ok, reason = _source_is_real(workspace, metadata, item.source, item.line)
        if ok:
            kept.append(item.model_copy(update={"verified": True}))
        else:
            rejected.append(f"{item.source}: {reason}")
            logger.warning("dropped ungrounded evidence: %s (%s)", item.source, reason)
    return kept, rejected


def ground_affected_files(
    workspace: Path, files: list[AffectedFile]
) -> tuple[list[AffectedFile], list[str]]:
    kept: list[AffectedFile] = []
    rejected: list[str] = []
    for entry in files:
        relative = entry.path.replace("\\", "/").lstrip("./")
        target = workspace / relative
        if target.exists() and target.is_file():
            kept.append(entry.model_copy(update={"path": relative}))
        else:
            rejected.append(f"{entry.path}: not present in the workspace")
    return kept, rejected


def from_ai(
    workspace: Path,
    metadata: ProjectMetadata,
    failure: NormalizedFailure,
    payload: AIDiagnosisResult,
) -> DiagnosisResult:
    """Convert model output into a grounded domain diagnosis."""
    evidence = [
        EvidenceItem(
            kind=EvidenceKind(item.kind),
            source=item.source,
            detail=item.detail,
            line=item.line or None,
            excerpt=item.excerpt or None,
        )
        for item in payload.evidence
        if item.source.strip() and item.detail.strip()
    ]
    grounded_evidence, rejected_evidence = ground_evidence(workspace, metadata, evidence)

    affected = [
        AffectedFile(
            path=entry.path,
            line_start=max(1, entry.line_start),
            line_end=max(1, entry.line_end or entry.line_start),
            reason=entry.reason,
        )
        for entry in payload.affected_files
    ]
    grounded_files, rejected_files = ground_affected_files(workspace, affected)

    rejected = rejected_evidence + rejected_files
    confidence = payload.confidence
    if rejected:
        # Ungrounded citations are a reliability signal; reflect that in confidence.
        confidence = min(confidence, 0.6)
    if not grounded_evidence:
        confidence = min(confidence, 0.3)

    try:
        severity = Severity(payload.severity)
    except ValueError:
        severity = failure.severity

    return DiagnosisResult(
        summary=payload.summary.strip(),
        root_cause=payload.root_cause.strip(),
        confidence=confidence,
        evidence=grounded_evidence,
        affected_files=grounded_files,
        affected_endpoint=(payload.affected_endpoint or "").strip() or failure.endpoint,
        severity=severity,
        hypotheses=[
            Hypothesis(
                statement=h.statement,
                confidence=h.confidence,
                supporting_evidence=h.supporting_evidence,
                status=h.status,
            )
            for h in payload.hypotheses
        ],
        failure_id=failure.id,
        reasoning_engine="openai",
        grounded=not rejected,
        ungrounded_evidence=rejected,
    )


def observed_facts(failure: NormalizedFailure, diagnosis: DiagnosisResult) -> list[str]:
    """The OBSERVED FACT rung of the ladder — only things measured, never inferred."""
    facts: list[str] = []
    if failure.endpoint and failure.status_code:
        facts.append(f"{failure.endpoint} returned HTTP {failure.status_code}.")
    if failure.test:
        facts.append(f"{failure.test} failed.")
    if failure.error_type and failure.error_type != "UnknownError":
        message = f": {failure.message}" if failure.message else ""
        facts.append(f"{failure.error_type} was raised{message}.")
    if failure.file and failure.line:
        facts.append(f"The exception surfaced at {failure.file}:{failure.line}.")
    for item in diagnosis.evidence:
        if item.verified and item.excerpt:
            location = f":{item.line}" if item.line else ""
            facts.append(f"{item.source}{location} contains: {item.excerpt.strip()[:160]}")
    return facts[:12]


def needs_stronger_evidence(diagnosis: DiagnosisResult, threshold: float = 0.35) -> bool:
    return diagnosis.confidence < threshold or not diagnosis.evidence
