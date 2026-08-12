"""Diagnosis models.

The epistemic vocabulary of API Doctor lives here. Every claim the system makes
is tagged with what kind of claim it is, so the UI can never present a
hypothesis as a verified result.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

from ..utils.timestamps import utcnow_iso
from .execution import Severity


class ClaimKind(str, Enum):
    """The six-level ladder from raw observation to verified outcome."""

    OBSERVED_FACT = "observed_fact"
    HYPOTHESIS = "hypothesis"
    ROOT_CAUSE = "root_cause"
    PROPOSED_FIX = "proposed_fix"
    TEST_RESULT = "test_result"
    VERIFIED_RESULT = "verified_result"


class EvidenceKind(str, Enum):
    STACK_TRACE = "stack_trace"
    SOURCE_CODE = "source_code"
    TEST_OUTPUT = "test_output"
    TEST_CODE = "test_code"
    API_RESPONSE = "api_response"
    API_CONTRACT = "api_contract"
    PROJECT_METADATA = "project_metadata"
    LOG = "log"


class EvidenceItem(BaseModel):
    """A single fact, anchored to a real artefact in the project.

    `source` must name something that exists (a file path, a pytest node id, an
    endpoint). Evidence that cannot be anchored is dropped by the grounding
    check in `agents/diagnostician.py` rather than shown to the developer.
    """

    kind: EvidenceKind = EvidenceKind.SOURCE_CODE
    source: str
    detail: str
    line: int | None = None
    excerpt: str | None = None
    verified: bool = False

    @field_validator("detail", "source")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("evidence fields must not be empty")
        return cleaned


class AffectedFile(BaseModel):
    path: str
    line_start: int = 1
    line_end: int = 1
    reason: str = ""

    @field_validator("line_end")
    @classmethod
    def _sane_range(cls, value: int) -> int:
        return max(1, value)


class Hypothesis(BaseModel):
    statement: str
    confidence: float = 0.5
    supporting_evidence: list[str] = Field(default_factory=list)
    status: str = "open"        # open | supported | rejected


class DiagnosisResult(BaseModel):
    """The agent's root-cause conclusion for one failure."""

    summary: str
    root_cause: str
    confidence: float = 0.0
    evidence: list[EvidenceItem] = Field(default_factory=list)
    affected_files: list[AffectedFile] = Field(default_factory=list)
    affected_endpoint: str | None = None
    severity: Severity = Severity.HIGH
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    failure_id: str | None = None
    reasoning_engine: str = "openai"
    grounded: bool = False
    ungrounded_evidence: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow_iso)

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class RepairPlanStep(BaseModel):
    order: int
    action: str
    target: str = ""
    rationale: str = ""


class RepairPlan(BaseModel):
    strategy: str
    steps: list[RepairPlanStep] = Field(default_factory=list)
    risk: str = "low"
    expected_outcome: str = ""
    tests_to_run: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow_iso)


class InvestigationStep(BaseModel):
    """One turn of the agent loop, recorded for the investigation report."""

    index: int
    tool: str
    arguments: dict = Field(default_factory=dict)
    result_summary: str = ""
    ok: bool = True
    duration_ms: int = 0
    at: str = Field(default_factory=utcnow_iso)


class Investigation(BaseModel):
    failure_id: str
    steps: list[InvestigationStep] = Field(default_factory=list)
    files_read: list[str] = Field(default_factory=list)
    searches: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    engine: str = "openai"
    iterations: int = 0
    started_at: str = Field(default_factory=utcnow_iso)
    finished_at: str | None = None
