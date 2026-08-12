"""Verification stage.

This module owns the product's central promise: **a repair is only VERIFIED when
a real test run proves it**.

`compute_verdict` derives the authoritative result from the pytest exit code and
the parsed run comparison. The model's `VerificationAnalysis` is collected for
explanation and retry guidance, and is explicitly allowed to be wrong — it can
never upgrade a failing run to a passing one. If the two disagree, the measured
result wins and the disagreement is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..ai.context_builder import as_prompt_json
from ..ai.openai_client import OpenAIClient
from ..ai.schemas import AIFailedRepairAnalysis
from ..execution.sandbox import Sandbox
from ..execution.test_runner import compare_runs, run_tests
from ..models.diagnosis import DiagnosisResult
from ..models.execution import NormalizedFailure, TestRunResult
from ..models.patch import PatchProposal
from ..models.report import VerificationAnalysis
from ..security.execution_security import ExecutionSecurityError, validate_test_selector
from ..utils.logging import get_logger
from .prompts import load_prompt

logger = get_logger(__name__)


@dataclass
class VerificationOutcome:
    """The measured result. `verified` here is ground truth."""

    verified: bool
    reason: str
    targeted: TestRunResult | None = None
    full: TestRunResult | None = None
    comparison: dict = field(default_factory=dict)
    original_failure_resolved: bool = False
    regressions: list[str] = field(default_factory=list)
    remaining_failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "verified": self.verified,
            "reason": self.reason,
            "original_failure_resolved": self.original_failure_resolved,
            "regressions": self.regressions,
            "remaining_failures": self.remaining_failures,
            "comparison": self.comparison,
        }


def _selectors_for(patch: PatchProposal, failure: NormalizedFailure) -> list[str]:
    candidates = list(patch.tests_to_run)
    if failure.test:
        candidates.insert(0, failure.test)
    valid: list[str] = []
    for candidate in candidates:
        try:
            valid.append(validate_test_selector(candidate))
        except ExecutionSecurityError:
            logger.warning("ignoring unusable test selector %r", candidate)
        if len(valid) >= 5:
            break
    return list(dict.fromkeys(valid))


async def verify_repair(
    sandbox: Sandbox,
    workspace: Path,
    baseline: TestRunResult | None,
    patch: PatchProposal,
    failure: NormalizedFailure,
) -> VerificationOutcome:
    """Run targeted tests, then the full suite, and decide from the results alone."""
    targeted: TestRunResult | None = None
    selectors = _selectors_for(patch, failure)
    if selectors:
        targeted = await run_tests(sandbox, workspace, selectors=selectors)
        if not targeted.all_passed:
            # The specific failure is still failing; the full suite cannot rescue it.
            remaining = [c.node_id for c in targeted.cases if c.outcome in {"failed", "error"}]
            return VerificationOutcome(
                verified=False,
                reason=(
                    f"the targeted test run still fails: {targeted.summary_line()}"
                ),
                targeted=targeted,
                original_failure_resolved=False,
                remaining_failures=remaining or selectors,
            )

    full = await run_tests(sandbox, workspace)
    comparison = compare_runs(baseline, full) if baseline else {}
    remaining = [c.node_id for c in full.cases if c.outcome in {"failed", "error"}]
    regressions = comparison.get("new_failures", []) if comparison else []

    original_resolved = True
    if failure.test:
        original_resolved = failure.test not in remaining
    elif targeted is not None:
        original_resolved = targeted.all_passed

    if full.all_passed:
        # A suite that passes because nothing ran is not a repair.
        if full.total == 0:
            return VerificationOutcome(
                verified=False,
                reason=(
                    "the test suite reported success but collected zero tests, so nothing "
                    "was actually verified"
                ),
                targeted=targeted,
                full=full,
                comparison=comparison,
                original_failure_resolved=False,
            )
        if baseline and full.passed < baseline.passed:
            return VerificationOutcome(
                verified=False,
                reason=(
                    f"the suite passes but only {full.passed} tests ran versus "
                    f"{baseline.passed} before the patch; tests appear to have been "
                    "removed or skipped rather than fixed"
                ),
                targeted=targeted,
                full=full,
                comparison=comparison,
                original_failure_resolved=False,
            )
        return VerificationOutcome(
            verified=True,
            reason=f"the full test suite passed: {full.summary_line()}",
            targeted=targeted,
            full=full,
            comparison=comparison,
            original_failure_resolved=original_resolved,
        )

    reason = f"the full test suite still fails: {full.summary_line()}"
    if regressions:
        reason = (
            f"the patch introduced {len(regressions)} regression(s): "
            f"{', '.join(regressions[:3])}"
        )
    return VerificationOutcome(
        verified=False,
        reason=reason,
        targeted=targeted,
        full=full,
        comparison=comparison,
        original_failure_resolved=original_resolved,
        regressions=regressions,
        remaining_failures=remaining,
    )


def offline_analysis(outcome: VerificationOutcome, attempt: int, max_attempts: int) -> VerificationAnalysis:
    """Deterministic interpretation of a measured outcome."""
    next_action = "stop"
    if not outcome.verified:
        next_action = "retry" if attempt < max_attempts else "rollback"
    guidance = ""
    if not outcome.verified:
        if outcome.regressions:
            guidance = (
                "The previous patch broke tests that previously passed: "
                f"{', '.join(outcome.regressions[:5])}. The next attempt must not change "
                "behaviour those tests depend on."
            )
        elif outcome.remaining_failures:
            guidance = (
                "These tests still fail after the patch: "
                f"{', '.join(outcome.remaining_failures[:5])}. The root cause was probably "
                "misidentified, or the fix was applied in the wrong place."
            )
    return VerificationAnalysis(
        verified=outcome.verified,
        verdict_reason=outcome.reason,
        original_failure_resolved=outcome.original_failure_resolved,
        regressions_introduced=bool(outcome.regressions),
        remaining_failures=outcome.remaining_failures,
        next_action=next_action,
        retry_guidance=guidance,
        confidence=1.0,      # measured, not estimated
        reasoning_engine="measured",
    )


async def analyze_with_ai(
    client: OpenAIClient,
    outcome: VerificationOutcome,
    patch: PatchProposal,
    diagnosis: DiagnosisResult,
    failure: NormalizedFailure,
    *,
    attempt: int,
    max_attempts: int,
) -> VerificationAnalysis:
    """Ask the model to explain the run. The measured verdict is not negotiable."""
    measured = offline_analysis(outcome, attempt, max_attempts)
    context = {
        "measured_result": {
            "verified": outcome.verified,
            "reason": outcome.reason,
            "note": (
                "This verdict was computed from the real pytest exit code. It is "
                "authoritative and cannot be changed by your analysis."
            ),
        },
        "failure_under_repair": {
            "error_type": failure.error_type,
            "message": failure.message,
            "test": failure.test,
            "endpoint": failure.endpoint,
        },
        "diagnosis": {"root_cause": diagnosis.root_cause, "confidence": diagnosis.confidence},
        "patch": {"title": patch.title, "explanation": patch.explanation, "diff": patch.diff[:8000]},
        "targeted_run": _run_payload(outcome.targeted),
        "full_run": _run_payload(outcome.full),
        "comparison": outcome.comparison,
        "attempt": attempt,
        "max_attempts": max_attempts,
    }
    try:
        payload = await client.analyze_verification(
            instructions=load_prompt("verification"), context=as_prompt_json(context)
        )
    except Exception as exc:  # noqa: BLE001 - analysis is advisory
        logger.warning("verification analysis unavailable: %s", exc)
        return measured

    next_action = payload.next_action
    if outcome.verified:
        next_action = "stop"
    elif attempt >= max_attempts and next_action == "retry":
        next_action = "rollback"

    return VerificationAnalysis(
        # Measured, never model-supplied.
        verified=outcome.verified,
        verdict_reason=payload.verdict_reason.strip() or outcome.reason,
        original_failure_resolved=(
            outcome.original_failure_resolved and payload.original_failure_resolved
        ),
        regressions_introduced=bool(outcome.regressions) or payload.regressions_introduced,
        remaining_failures=outcome.remaining_failures or payload.remaining_failures,
        next_action=next_action,
        retry_guidance=payload.retry_guidance.strip() or measured.retry_guidance,
        confidence=payload.confidence,
        reasoning_engine="openai",
    )


def _run_payload(run: TestRunResult | None) -> dict:
    if run is None:
        return {"ran": False}
    return {
        "ran": True,
        "exit_code": run.exit_code,
        "passed": run.passed,
        "failed": run.failed,
        "errors": run.errors,
        "total": run.total,
        "all_passed": run.all_passed,
        "stdout_tail": run.stdout[-6000:],
        "failing_tests": [c.node_id for c in run.cases if c.outcome in {"failed", "error"}],
    }


async def analyze_failed_repair(
    client: OpenAIClient,
    outcome: VerificationOutcome,
    patch: PatchProposal,
    diagnosis: DiagnosisResult,
    failure: NormalizedFailure,
    previous_attempts: list[dict],
) -> AIFailedRepairAnalysis | None:
    """Post-mortem that steers the next attempt."""
    context = {
        "failure": {
            "error_type": failure.error_type,
            "message": failure.message,
            "file": failure.file,
            "line": failure.line,
            "test": failure.test,
            "endpoint": failure.endpoint,
        },
        "diagnosis_that_failed": {
            "root_cause": diagnosis.root_cause,
            "confidence": diagnosis.confidence,
            "evidence": [f"{e.source}: {e.detail}" for e in diagnosis.evidence],
        },
        "patch_that_failed": {
            "title": patch.title,
            "explanation": patch.explanation,
            "diff": patch.diff[:8000],
        },
        "verification_result": outcome.as_dict(),
        "test_output": (outcome.full.stdout[-8000:] if outcome.full else ""),
        "all_previous_attempts": previous_attempts,
    }
    try:
        return await client.analyze_failed_repair(
            instructions=load_prompt("retry"), context=as_prompt_json(context)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed-repair analysis unavailable: %s", exc)
        return None
