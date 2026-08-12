"""Repair session + report models.

`RepairSession` is the unit of work the whole product revolves around: one
detected failure, N attempts, each with a diagnosis, a patch, an application and
a verification, ending in a verdict that is only ever `verified` when a real
test run proved it.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from ..utils.timestamps import utcnow_iso
from .diagnosis import DiagnosisResult, Investigation, RepairPlan
from .execution import NormalizedFailure, TestRunResult
from .patch import AppliedPatch, PatchProposal, PatchValidation


class RepairStage(str, Enum):
    OBSERVE = "observe"
    INVESTIGATE = "investigate"
    DIAGNOSE = "diagnose"
    PLAN = "plan"
    GENERATE_PATCH = "generate_patch"
    VALIDATE_PATCH = "validate_patch"
    AWAIT_APPROVAL = "await_approval"
    APPLY = "apply"
    VERIFY = "verify"
    RETRY = "retry"
    DONE = "done"


class RepairVerdict(str, Enum):
    """Deliberately explicit. There is no ambiguous "success" value."""

    PENDING = "pending"
    NO_FAILURE_DETECTED = "no_failure_detected"
    AWAITING_APPROVAL = "awaiting_approval"
    VERIFIED = "verified"
    PATCH_APPLIED_UNVERIFIED = "patch_applied_unverified"
    REPAIR_FAILED = "repair_failed"
    REJECTED_BY_DEVELOPER = "rejected_by_developer"
    ABORTED = "aborted"
    ERROR = "error"


class VerificationAnalysis(BaseModel):
    """The agent's read of a post-apply test run — advisory only.

    The authoritative pass/fail is `verified`, which is computed from the actual
    test exit code, never from model output.
    """

    verified: bool = False
    verdict_reason: str = ""
    original_failure_resolved: bool = False
    regressions_introduced: bool = False
    remaining_failures: list[str] = Field(default_factory=list)
    next_action: str = "stop"          # stop | retry | rollback
    retry_guidance: str = ""
    confidence: float = 0.0
    reasoning_engine: str = "openai"


class RepairAttempt(BaseModel):
    attempt: int
    started_at: str = Field(default_factory=utcnow_iso)
    finished_at: str | None = None
    investigation: Investigation | None = None
    diagnosis: DiagnosisResult | None = None
    plan: RepairPlan | None = None
    patch: PatchProposal | None = None
    validation: PatchValidation | None = None
    applied: AppliedPatch | None = None
    targeted_test: TestRunResult | None = None
    full_test: TestRunResult | None = None
    verification: VerificationAnalysis | None = None
    verified: bool = False
    outcome: str = "pending"
    failure_reason: str | None = None
    rolled_back: bool = False


class RepairSession(BaseModel):
    id: str
    project_id: str
    project_name: str = ""
    created_at: str = Field(default_factory=utcnow_iso)
    finished_at: str | None = None
    stage: RepairStage = RepairStage.OBSERVE
    verdict: RepairVerdict = RepairVerdict.PENDING
    mode: str = "test"
    reasoning_engine: str = "openai"
    execution_runner: str = "local"
    isolated_execution: bool = False
    baseline: TestRunResult | None = None
    baseline_failures: list[NormalizedFailure] = Field(default_factory=list)
    target_failure: NormalizedFailure | None = None
    attempts: list[RepairAttempt] = Field(default_factory=list)
    max_attempts: int = 3
    require_approval: bool = True
    pending_patch_id: str | None = None
    summary: str = ""
    error: str | None = None
    duration_ms: int = 0

    @property
    def current_attempt(self) -> RepairAttempt | None:
        return self.attempts[-1] if self.attempts else None

    @property
    def verified(self) -> bool:
        return self.verdict == RepairVerdict.VERIFIED

    def attempt_count(self) -> int:
        return len(self.attempts)


class RepairSessionSummary(BaseModel):
    id: str
    project_id: str
    project_name: str
    created_at: str
    finished_at: str | None = None
    verdict: RepairVerdict
    stage: RepairStage
    attempts: int = 0
    verified: bool = False
    reasoning_engine: str = "openai"
    target: str | None = None
    summary: str = ""
    duration_ms: int = 0

    @classmethod
    def from_session(cls, session: RepairSession) -> "RepairSessionSummary":
        return cls(
            id=session.id,
            project_id=session.project_id,
            project_name=session.project_name,
            created_at=session.created_at,
            finished_at=session.finished_at,
            verdict=session.verdict,
            stage=session.stage,
            attempts=len(session.attempts),
            verified=session.verified,
            reasoning_engine=session.reasoning_engine,
            target=session.target_failure.headline() if session.target_failure else None,
            summary=session.summary,
            duration_ms=session.duration_ms,
        )


class DashboardStats(BaseModel):
    projects: int = 0
    failures_detected: int = 0
    repairs_attempted: int = 0
    repairs_verified: int = 0
    repair_success_rate: float = 0.0
    average_repair_attempts: float = 0.0
    average_repair_seconds: float = 0.0
    sessions: int = 0
    reasoning_engine: str = "openai"
    execution_mode: str = "local"
    isolated_execution: bool = False


class RecentFailure(BaseModel):
    project_id: str
    project_name: str
    session_id: str | None = None
    endpoint: str | None = None
    test: str | None = None
    error_type: str = ""
    message: str = ""
    status_code: int | None = None
    detected_at: str = ""
    status: str = "Repair Available"
    verdict: RepairVerdict | None = None


class InvestigationReport(BaseModel):
    """Human-readable end-to-end report for one repair session."""

    session_id: str
    project_id: str
    project_name: str
    generated_at: str = Field(default_factory=utcnow_iso)
    verdict: RepairVerdict
    verified: bool
    headline: str
    observed_facts: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    root_cause: str | None = None
    evidence: list[dict] = Field(default_factory=list)
    proposed_fix: str | None = None
    diff: str | None = None
    test_results: list[dict] = Field(default_factory=list)
    verification: dict | None = None
    timeline: list[dict] = Field(default_factory=list)
    attempts: int = 0
    reasoning_engine: str = "openai"
    execution_runner: str = "local"
    isolated_execution: bool = False
    disclaimer: str = ""
    markdown: str = ""
