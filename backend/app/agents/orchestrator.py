"""The single repair orchestrator.

One agent, one state machine, one place where the decision to write to a
developer's files is made:

    OBSERVE -> INVESTIGATE -> DIAGNOSE -> PLAN -> GENERATE_PATCH
            -> VALIDATE_PATCH -> [AWAIT_APPROVAL] -> APPLY -> VERIFY
            -> (VERIFIED | RETRY | REPAIR_FAILED)

Invariants this class enforces:

* No patch is applied unless it validated against the real files.
* No patch is applied without developer approval when approval is required.
* A failed verification always rolls the workspace back before retrying, so
  every attempt starts from the original code rather than compounding edits.
* The verdict is VERIFIED only when a real test run passed. There is no path
  through this file that sets VERIFIED from model output.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Awaitable, Callable

from ..ai.openai_client import (
    AIError,
    AINotConfiguredError,
    OpenAIClient,
    StructuredOutputError,
)
from ..config.settings import Settings
from ..execution.api_runner import run_api_probe
from ..execution.sandbox import Sandbox
from ..execution.test_runner import run_tests
from ..models.diagnosis import DiagnosisResult, RepairPlan
from ..models.events import AgentEvent, EventLevel, EventType
from ..models.execution import NormalizedFailure, RunMode, TestRunResult
from ..models.patch import PatchProposal, PatchStatus, PatchValidation
from ..models.project import ProjectMetadata
from ..models.report import (
    RepairAttempt,
    RepairSession,
    RepairStage,
    RepairVerdict,
    VerificationAnalysis,
)
from ..patches.patch_applier import PatchApplyError, apply_patch
from ..patches.patch_validator import validate_patch
from ..patches.rollback_manager import RollbackError, rollback_patch
from ..patches.snapshot_manager import SnapshotManager
from ..utils.logging import get_logger
from ..utils.timestamps import elapsed_ms, monotonic_ms, utcnow_iso
from . import diagnostician, investigator, offline_engine, patch_generator, verifier
from .tools import ToolContext

logger = get_logger(__name__)

EventSink = Callable[[AgentEvent], Awaitable[None]]


class ApprovalGate:
    """Suspends the run until a developer approves or rejects the patch."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self.approved: bool | None = None
        self.note: str | None = None

    def decide(self, approved: bool, note: str | None = None) -> None:
        self.approved = approved
        self.note = note
        self._event.set()

    async def wait(self, timeout: float) -> bool | None:
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return self.approved


class RepairOrchestrator:
    def __init__(
        self,
        *,
        settings: Settings,
        workspace: Path,
        metadata: ProjectMetadata,
        sandbox: Sandbox,
        snapshots: SnapshotManager,
        project_id: str,
        project_name: str,
        ai_client: OpenAIClient | None,
        emit: EventSink | None = None,
    ) -> None:
        self.settings = settings
        self.workspace = workspace
        self.metadata = metadata
        self.sandbox = sandbox
        self.snapshots = snapshots
        self.project_id = project_id
        self.project_name = project_name
        self.ai = ai_client if (ai_client and ai_client.configured) else None
        self._emit = emit
        self.engine = "openai" if self.ai else offline_engine.ENGINE_NAME
        self.session: RepairSession | None = None
        self.approval = ApprovalGate()
        self.openapi: dict | None = None
        self._ai_degraded = False

    # ------------------------------------------------------------- events --
    async def emit(
        self,
        event_type: EventType,
        message: str,
        *,
        level: EventLevel = EventLevel.INFO,
        stage: str | None = None,
        attempt: int | None = None,
        **data,
    ) -> None:
        if self._emit is None:
            return
        await self._emit(
            AgentEvent(
                type=event_type,
                level=level,
                message=message,
                project_id=self.project_id,
                session_id=self.session.id if self.session else None,
                stage=stage,
                attempt=attempt,
                data=data,
            )
        )

    async def _stage(self, stage: RepairStage, message: str, attempt: int | None = None) -> None:
        if self.session:
            self.session.stage = stage
        await self.emit(
            EventType.STAGE_STARTED, message, stage=stage.value, attempt=attempt
        )

    # -------------------------------------------------------- entry point --
    async def run(
        self,
        *,
        mode: RunMode = RunMode.TEST,
        target_failure_id: str | None = None,
        auto_approve: bool | None = None,
        approval_timeout: float = 900.0,
    ) -> RepairSession:
        started = monotonic_ms()
        require_approval = (
            self.settings.require_approval if auto_approve is None else not auto_approve
        )
        session = RepairSession(
            id=f"sess_{uuid.uuid4().hex[:12]}",
            project_id=self.project_id,
            project_name=self.project_name,
            mode=mode.value,
            reasoning_engine=self.engine,
            execution_runner=self.sandbox.kind,
            isolated_execution=self.sandbox.capabilities().isolated,
            max_attempts=self.settings.max_repair_attempts,
            require_approval=require_approval,
        )
        self.session = session

        await self.emit(
            EventType.SESSION_STARTED,
            f"Repair session started for {self.project_name}",
            engine=self.engine,
            runner=self.sandbox.kind,
            isolated=session.isolated_execution,
            mode=mode.value,
        )

        try:
            failure = await self._observe(session, mode, target_failure_id)
            if failure is None:
                session.verdict = RepairVerdict.NO_FAILURE_DETECTED
                session.summary = "No failures were detected. There is nothing to repair."
                session.stage = RepairStage.DONE
                await self.emit(
                    EventType.NO_FAILURES,
                    session.summary,
                    level=EventLevel.SUCCESS,
                )
                return self._finish(session, started)

            session.target_failure = failure
            await self._repair_loop(session, failure, require_approval, approval_timeout)
        except AINotConfiguredError as exc:
            session.verdict = RepairVerdict.ERROR
            session.error = str(exc)
            session.summary = "AI provider is not configured."
            await self.emit(EventType.ERROR, str(exc), level=EventLevel.ERROR)
        except (AIError, StructuredOutputError) as exc:
            session.verdict = RepairVerdict.ABORTED
            session.error = str(exc)
            session.summary = (
                "The run stopped safely because the AI response could not be validated. "
                "No changes were made to your code."
            )
            await self.emit(EventType.ERROR, str(exc), level=EventLevel.ERROR)
        except asyncio.CancelledError:
            session.verdict = RepairVerdict.ABORTED
            session.summary = "The repair run was cancelled."
            raise
        except Exception as exc:  # noqa: BLE001 - surface, never swallow
            logger.exception("repair session failed")
            session.verdict = RepairVerdict.ERROR
            session.error = f"{type(exc).__name__}: {exc}"
            session.summary = "The repair run failed with an internal error."
            await self.emit(EventType.ERROR, session.error, level=EventLevel.ERROR)

        return self._finish(session, started)

    def _finish(self, session: RepairSession, started: float) -> RepairSession:
        session.finished_at = utcnow_iso()
        session.duration_ms = elapsed_ms(started)
        if session.stage is not RepairStage.AWAIT_APPROVAL:
            session.stage = RepairStage.DONE
        return session

    # ------------------------------------------------------------ observe --
    async def _observe(
        self, session: RepairSession, mode: RunMode, target_failure_id: str | None
    ) -> NormalizedFailure | None:
        await self._stage(RepairStage.OBSERVE, "Detecting failures")
        await self.emit(
            EventType.EXECUTION_STARTED,
            f"Running {'the test suite' if mode is RunMode.TEST else 'API probes'} "
            f"in {self.sandbox.kind} mode",
            mode=mode.value,
        )

        failures: list[NormalizedFailure] = []
        if mode is RunMode.TEST:
            baseline = await run_tests(self.sandbox, self.workspace)
            session.baseline = baseline
            failures = list(baseline.failures)
            await self.emit(
                EventType.EXECUTION_FINISHED,
                f"Test run finished: {baseline.summary_line()}",
                level=EventLevel.WARNING if not baseline.all_passed else EventLevel.SUCCESS,
                exit_code=baseline.exit_code,
                passed=baseline.passed,
                failed=baseline.failed,
                errors=baseline.errors,
                total=baseline.total,
                duration_ms=baseline.duration_ms,
            )
        else:
            api_result = await run_api_probe(self.sandbox, self.workspace, self.metadata)
            self.openapi = api_result.openapi
            failures = list(api_result.failures)
            await self.emit(
                EventType.EXECUTION_FINISHED,
                (
                    f"Probed {len(api_result.probes)} endpoint(s); "
                    f"{len(failures)} failing"
                    if api_result.started
                    else f"The API failed to start: {(api_result.startup_error or '')[:200]}"
                ),
                level=EventLevel.WARNING if failures else EventLevel.SUCCESS,
                probes=[
                    {
                        "method": p.method, "path": p.path, "status": p.status_code,
                        "latency_ms": p.latency_ms, "ok": p.ok,
                    }
                    for p in api_result.probes
                ],
            )
            # A baseline test run still gives verification something to compare against.
            if self.metadata.test_files:
                session.baseline = await run_tests(self.sandbox, self.workspace)

        session.baseline_failures = failures
        if not failures:
            return None

        for failure in failures:
            await self.emit(
                EventType.FAILURE_DETECTED,
                failure.headline(),
                level=EventLevel.ERROR,
                failure_id=failure.id,
                error_type=failure.error_type,
                file=failure.file,
                line=failure.line,
                test=failure.test,
                endpoint=failure.endpoint,
                status_code=failure.status_code,
                severity=failure.severity.value,
            )

        if target_failure_id:
            chosen = next((f for f in failures if f.id == target_failure_id), None)
            if chosen is not None:
                return chosen
            await self.emit(
                EventType.WARNING,
                f"Requested failure {target_failure_id} was not detected in this run; "
                "repairing the highest-severity failure instead.",
                level=EventLevel.WARNING,
            )

        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(failures, key=lambda f: severity_rank.get(f.severity.value, 9))[0]

    # -------------------------------------------------------- repair loop --
    async def _repair_loop(
        self,
        session: RepairSession,
        failure: NormalizedFailure,
        require_approval: bool,
        approval_timeout: float,
    ) -> None:
        previous_attempts: list[dict] = []
        retry_guidance = ""

        for attempt_number in range(1, session.max_attempts + 1):
            attempt = RepairAttempt(attempt=attempt_number)
            session.attempts.append(attempt)
            await self.emit(
                EventType.STAGE_STARTED,
                f"Repair attempt {attempt_number} of {session.max_attempts}",
                stage=RepairStage.INVESTIGATE.value,
                attempt=attempt_number,
            )

            ctx = ToolContext(
                workspace=self.workspace,
                metadata=self.metadata,
                settings=self.settings,
                sandbox=self.sandbox,
                failure=failure,
                openapi=self.openapi,
                baseline=session.baseline,
            )

            # ---------------------------------------------- investigate ---
            await self._stage(RepairStage.INVESTIGATE, "Investigating the failure", attempt_number)
            diagnosis, plan, rule_outcome = await self._investigate_and_diagnose(
                ctx, failure, session, attempt, previous_attempts, retry_guidance
            )
            attempt.diagnosis = diagnosis
            attempt.plan = plan

            await self.emit(
                EventType.DIAGNOSIS_READY,
                diagnosis.root_cause[:400],
                level=EventLevel.INFO,
                stage=RepairStage.DIAGNOSE.value,
                attempt=attempt_number,
                confidence=diagnosis.confidence,
                grounded=diagnosis.grounded,
                evidence_count=len(diagnosis.evidence),
                engine=diagnosis.reasoning_engine,
                ungrounded=diagnosis.ungrounded_evidence,
            )

            if diagnosis.confidence <= 0.0 and rule_outcome is None and self.ai is None:
                attempt.outcome = "no_diagnosis"
                attempt.failure_reason = (
                    "The deterministic offline engine has no rule for this failure class."
                )
                attempt.finished_at = utcnow_iso()
                session.verdict = RepairVerdict.REPAIR_FAILED
                session.summary = (
                    f"Detected {failure.error_type} in "
                    f"{failure.endpoint or failure.test or failure.file}, but no root cause "
                    "was established. Offline mode covers a fixed set of failure classes; "
                    "set OPENAI_API_KEY to enable AI-powered investigation."
                )
                await self.emit(
                    EventType.VERIFICATION_FAILED, session.summary, level=EventLevel.WARNING
                )
                return

            # -------------------------------------------- generate patch ---
            await self._stage(RepairStage.GENERATE_PATCH, "Generating a minimal patch", attempt_number)
            patch, validation = await self._generate_patch(
                failure, diagnosis, plan, rule_outcome, attempt_number,
                previous_attempts, retry_guidance,
            )
            attempt.patch = patch
            attempt.validation = validation

            if patch is None or validation is None or not validation.valid:
                reasons = (
                    "; ".join(issue.message for issue in validation.errors)
                    if validation else "no patch could be generated"
                )
                await self.emit(
                    EventType.PATCH_REJECTED,
                    f"Patch rejected before application: {reasons}",
                    level=EventLevel.WARNING,
                    attempt=attempt_number,
                    issues=[i.model_dump(mode="json") for i in (validation.issues if validation else [])],
                )
                attempt.outcome = "patch_rejected"
                attempt.failure_reason = reasons
                attempt.finished_at = utcnow_iso()
                previous_attempts.append(self._attempt_summary(attempt, "patch failed validation"))
                retry_guidance = (
                    "The previous patch was rejected by the validator before it was applied: "
                    f"{reasons}. Copy anchor text verbatim from the file."
                )
                if attempt_number >= session.max_attempts:
                    session.verdict = RepairVerdict.REPAIR_FAILED
                    session.summary = (
                        f"No applicable patch was produced after {attempt_number} attempt(s). "
                        "Your code was not modified."
                    )
                    return
                await self.emit(
                    EventType.RETRY_SCHEDULED,
                    "Retrying with the validator feedback",
                    level=EventLevel.WARNING,
                    attempt=attempt_number,
                )
                continue

            await self.emit(
                EventType.PATCH_VALIDATED,
                f"Patch validated: {patch.title}",
                level=EventLevel.SUCCESS,
                stage=RepairStage.VALIDATE_PATCH.value,
                attempt=attempt_number,
                patch_id=patch.id,
                files=validation.files_touched,
                lines_added=validation.lines_added,
                lines_removed=validation.lines_removed,
                diff=validation.diff[:20000],
                explanation=patch.explanation,
                confidence=patch.confidence,
            )

            # ------------------------------------------------- approval ---
            if require_approval:
                session.stage = RepairStage.AWAIT_APPROVAL
                session.pending_patch_id = patch.id
                session.verdict = RepairVerdict.AWAITING_APPROVAL
                patch.status = PatchStatus.AWAITING_APPROVAL
                await self.emit(
                    EventType.AWAITING_APPROVAL,
                    "Waiting for developer approval before applying the patch",
                    level=EventLevel.WARNING,
                    attempt=attempt_number,
                    patch_id=patch.id,
                    diff=validation.diff[:20000],
                )
                decision = await self.approval.wait(approval_timeout)
                if decision is None:
                    session.verdict = RepairVerdict.AWAITING_APPROVAL
                    session.summary = (
                        "The proposed patch is waiting for approval. Nothing has been applied."
                    )
                    attempt.outcome = "awaiting_approval"
                    return
                if not decision:
                    patch.status = PatchStatus.REJECTED
                    session.verdict = RepairVerdict.REJECTED_BY_DEVELOPER
                    session.summary = "The developer rejected the proposed patch. No changes were made."
                    attempt.outcome = "rejected_by_developer"
                    attempt.finished_at = utcnow_iso()
                    await self.emit(
                        EventType.PATCH_REJECTED,
                        session.summary,
                        level=EventLevel.WARNING,
                        attempt=attempt_number,
                    )
                    return
                self.approval = ApprovalGate()   # rearm for the next attempt
                session.pending_patch_id = None

            # ---------------------------------------------------- apply ---
            await self._stage(RepairStage.APPLY, "Applying the patch", attempt_number)
            try:
                applied, validation = apply_patch(
                    self.workspace, patch, self.snapshots, self.settings
                )
            except PatchApplyError as exc:
                attempt.outcome = "apply_failed"
                attempt.failure_reason = str(exc)
                attempt.finished_at = utcnow_iso()
                await self.emit(
                    EventType.ERROR, f"Patch could not be applied: {exc}", level=EventLevel.ERROR
                )
                previous_attempts.append(self._attempt_summary(attempt, str(exc)))
                if attempt_number >= session.max_attempts:
                    session.verdict = RepairVerdict.REPAIR_FAILED
                    session.summary = f"The patch could not be applied: {exc}"
                    return
                continue

            attempt.applied = applied
            attempt.validation = validation
            await self.emit(
                EventType.PATCH_APPLIED,
                f"Applied patch to {', '.join(applied.files_changed)}",
                level=EventLevel.SUCCESS,
                attempt=attempt_number,
                patch_id=patch.id,
                snapshot_id=applied.snapshot_id,
                files=applied.files_changed,
            )

            # --------------------------------------------------- verify ---
            await self._stage(RepairStage.VERIFY, "Verifying the repair against the real tests", attempt_number)
            await self.emit(
                EventType.VERIFICATION_STARTED,
                "Running targeted tests, then the full suite",
                attempt=attempt_number,
            )
            outcome = await verifier.verify_repair(
                self.sandbox, self.workspace, session.baseline, patch, failure
            )
            attempt.targeted_test = outcome.targeted
            attempt.full_test = outcome.full

            analysis = await self._verification_analysis(
                outcome, patch, diagnosis, failure, attempt_number, session.max_attempts
            )
            attempt.verification = analysis
            attempt.verified = outcome.verified

            if outcome.verified:
                attempt.outcome = "verified"
                attempt.finished_at = utcnow_iso()
                session.verdict = RepairVerdict.VERIFIED
                session.stage = RepairStage.DONE
                full = outcome.full
                session.summary = (
                    f"FIX VERIFIED — {patch.title}. "
                    f"{full.passed}/{full.total} tests passed after the patch."
                    if full else f"FIX VERIFIED — {patch.title}."
                )
                await self.emit(
                    EventType.VERIFICATION_PASSED,
                    session.summary,
                    level=EventLevel.SUCCESS,
                    attempt=attempt_number,
                    passed=full.passed if full else 0,
                    total=full.total if full else 0,
                    duration_ms=full.duration_ms if full else 0,
                    reason=outcome.reason,
                )
                return

            # ------------------------------------------ failed: rollback ---
            attempt.outcome = "verification_failed"
            attempt.failure_reason = outcome.reason
            await self.emit(
                EventType.VERIFICATION_FAILED,
                f"Repair not verified: {outcome.reason}",
                level=EventLevel.ERROR,
                attempt=attempt_number,
                remaining_failures=outcome.remaining_failures,
                regressions=outcome.regressions,
            )

            try:
                rollback_patch(
                    self.workspace, applied, self.snapshots,
                    reason=f"verification failed on attempt {attempt_number}", patch=patch,
                )
                attempt.rolled_back = True
                await self.emit(
                    EventType.PATCH_ROLLED_BACK,
                    f"Workspace restored to its state before attempt {attempt_number}",
                    level=EventLevel.WARNING,
                    attempt=attempt_number,
                    files=applied.files_changed,
                )
            except RollbackError as exc:
                await self.emit(
                    EventType.ERROR,
                    f"Rollback failed: {exc}. The workspace may contain the failed patch.",
                    level=EventLevel.ERROR,
                )
                session.verdict = RepairVerdict.ERROR
                session.error = str(exc)
                session.summary = (
                    "Verification failed and the automatic rollback also failed. "
                    "Inspect the workspace before retrying."
                )
                attempt.finished_at = utcnow_iso()
                return

            attempt.finished_at = utcnow_iso()
            previous_attempts.append(self._attempt_summary(attempt, outcome.reason))

            if analysis.next_action == "rollback" or attempt_number >= session.max_attempts:
                session.verdict = RepairVerdict.REPAIR_FAILED
                session.summary = (
                    f"REPAIR FAILED after {attempt_number} attempt(s). {outcome.reason} "
                    "The workspace was rolled back; your code is unchanged."
                )
                return

            retry_guidance = await self._retry_guidance(
                outcome, patch, diagnosis, failure, previous_attempts, analysis
            )
            if retry_guidance is None:
                session.verdict = RepairVerdict.REPAIR_FAILED
                session.summary = (
                    f"REPAIR FAILED after {attempt_number} attempt(s). Further attempts were "
                    "judged unlikely to succeed. The workspace was rolled back."
                )
                return

            await self.emit(
                EventType.RETRY_SCHEDULED,
                f"Retrying with new guidance: {retry_guidance[:240]}",
                level=EventLevel.WARNING,
                attempt=attempt_number,
                next_attempt=attempt_number + 1,
            )

        session.verdict = RepairVerdict.REPAIR_FAILED
        session.summary = (
            f"REPAIR FAILED after {session.max_attempts} attempts. The workspace was rolled back."
        )

    # ----------------------------------------------------------- helpers --
    async def _investigate_and_diagnose(
        self,
        ctx: ToolContext,
        failure: NormalizedFailure,
        session: RepairSession,
        attempt: RepairAttempt,
        previous_attempts: list[dict],
        retry_guidance: str,
    ) -> tuple[DiagnosisResult, RepairPlan | None, offline_engine.RuleOutcome | None]:
        if self.ai is not None:
            try:
                investigation, ai_diagnosis = await investigator.investigate_with_ai(
                    self.ai, ctx, failure,
                    test_run=session.baseline,
                    previous_attempts=previous_attempts,
                    retry_guidance=retry_guidance,
                    on_tool_call=self._on_tool_call,
                    on_tool_result=self._on_tool_result,
                )
                attempt.investigation = investigation
                diagnosis = diagnostician.from_ai(
                    self.workspace, self.metadata, failure, ai_diagnosis
                )
                if diagnosis.ungrounded_evidence:
                    await self.emit(
                        EventType.WARNING,
                        (
                            f"{len(diagnosis.ungrounded_evidence)} evidence item(s) could not be "
                            "verified against the workspace and were removed."
                        ),
                        level=EventLevel.WARNING,
                        dropped=diagnosis.ungrounded_evidence,
                    )
                return diagnosis, None, None
            except (AIError, StructuredOutputError) as exc:
                # Degrade honestly rather than aborting the whole run.
                self._ai_degraded = True
                logger.warning("AI investigation failed, falling back to offline rules: %s", exc)
                await self.emit(
                    EventType.WARNING,
                    f"AI investigation failed ({exc}). Falling back to the deterministic engine.",
                    level=EventLevel.WARNING,
                )

        investigation = await investigator.investigate_offline(
            ctx, failure, on_step=self._on_offline_step
        )
        attempt.investigation = investigation
        diagnosis, rule_outcome = offline_engine.diagnose(self.workspace, self.metadata, failure)
        plan = offline_engine.build_plan(rule_outcome, failure)
        return diagnosis, plan, rule_outcome

    async def _generate_patch(
        self,
        failure: NormalizedFailure,
        diagnosis: DiagnosisResult,
        plan: RepairPlan | None,
        rule_outcome: offline_engine.RuleOutcome | None,
        attempt_number: int,
        previous_attempts: list[dict],
        retry_guidance: str,
    ) -> tuple[PatchProposal | None, PatchValidation | None]:
        if self.ai is not None and not self._ai_degraded:
            try:
                patch, validation = await patch_generator.generate_with_ai(
                    self.ai, self.workspace, self.metadata, failure, diagnosis, plan,
                    self.settings,
                    project_id=self.project_id,
                    attempt=attempt_number,
                    previous_attempts=previous_attempts,
                    retry_guidance=retry_guidance,
                )
            except (AIError, StructuredOutputError) as exc:
                logger.warning("AI patch generation failed: %s", exc)
                await self.emit(
                    EventType.WARNING,
                    f"AI patch generation failed ({exc}).",
                    level=EventLevel.WARNING,
                )
                return None, None

            touched_tests = patch_generator.touches_tests(patch, self.metadata)
            if touched_tests:
                from ..models.patch import ValidationIssue

                validation.valid = False
                validation.issues.append(
                    ValidationIssue(
                        severity="error",
                        code="modifies_tests",
                        message=(
                            "The patch modifies test files "
                            f"({', '.join(touched_tests)}). Tests define correct behaviour and "
                            "are never edited to force a pass."
                        ),
                    )
                )
                return patch, validation

            if validation.valid:
                review = await patch_generator.review_with_ai(
                    self.ai, patch, diagnosis, validation, self.metadata
                )
                if review is not None:
                    await self.emit(
                        EventType.AGENT_MESSAGE,
                        (
                            "Patch review: approved"
                            if review.approve
                            else f"Patch review raised concerns: {'; '.join(review.concerns)[:300]}"
                        ),
                        level=EventLevel.INFO if review.approve else EventLevel.WARNING,
                        approve=review.approve,
                        concerns=review.concerns,
                        addresses_root_cause=review.addresses_root_cause,
                        is_minimal=review.is_minimal,
                    )
                    if review.revised_explanation.strip():
                        patch.explanation = review.revised_explanation.strip()
                    if not review.approve:
                        from ..models.patch import ValidationIssue

                        validation.valid = False
                        validation.issues.append(
                            ValidationIssue(
                                severity="error",
                                code="review_rejected",
                                message="Second-opinion review rejected the patch: "
                                + "; ".join(review.concerns)[:500],
                            )
                        )
            return patch, validation

        if rule_outcome is None:
            return None, None
        patch = offline_engine.build_patch(
            rule_outcome, project_id=self.project_id, failure=failure, attempt=attempt_number
        )
        validation = validate_patch(self.workspace, patch, self.settings)
        if validation.valid:
            patch.status = PatchStatus.VALIDATED
            patch.diff = validation.diff
            patch.stats = {
                "lines_added": validation.lines_added,
                "lines_removed": validation.lines_removed,
                "files": len(validation.files_touched),
            }
        return patch, validation

    async def _verification_analysis(
        self, outcome, patch, diagnosis, failure, attempt_number, max_attempts
    ) -> VerificationAnalysis:
        if self.ai is not None and not self._ai_degraded:
            return await verifier.analyze_with_ai(
                self.ai, outcome, patch, diagnosis, failure,
                attempt=attempt_number, max_attempts=max_attempts,
            )
        return verifier.offline_analysis(outcome, attempt_number, max_attempts)

    async def _retry_guidance(
        self, outcome, patch, diagnosis, failure, previous_attempts, analysis
    ) -> str | None:
        """Returns guidance for the next attempt, or None to stop trying."""
        if self.ai is not None and not self._ai_degraded:
            post_mortem = await verifier.analyze_failed_repair(
                self.ai, outcome, patch, diagnosis, failure, previous_attempts
            )
            if post_mortem is not None:
                await self.emit(
                    EventType.AGENT_MESSAGE,
                    f"Post-mortem: {post_mortem.why_it_failed[:300]}",
                    level=EventLevel.WARNING,
                    diagnosis_was_wrong=post_mortem.was_diagnosis_wrong,
                    investigate=post_mortem.what_to_investigate,
                    should_retry=post_mortem.should_retry,
                )
                if not post_mortem.should_retry:
                    return None
                parts = [post_mortem.why_it_failed]
                if post_mortem.was_diagnosis_wrong and post_mortem.revised_root_cause:
                    parts.append(f"Revised root cause: {post_mortem.revised_root_cause}")
                if post_mortem.what_to_investigate:
                    parts.append("Investigate: " + ", ".join(post_mortem.what_to_investigate))
                if post_mortem.different_approach:
                    parts.append(f"Try instead: {post_mortem.different_approach}")
                return " ".join(parts)
        return analysis.retry_guidance or (
            "The previous patch did not fix the failure. Consider a different root cause."
        )

    def _attempt_summary(self, attempt: RepairAttempt, reason: str) -> dict:
        return {
            "attempt": attempt.attempt,
            "root_cause": attempt.diagnosis.root_cause if attempt.diagnosis else None,
            "patch_title": attempt.patch.title if attempt.patch else None,
            "diff": (attempt.patch.diff[:4000] if attempt.patch and attempt.patch.diff else None),
            "why_it_failed": reason,
            "rolled_back": attempt.rolled_back,
        }

    # ----------------------------------------------------- event adapters --
    async def _on_tool_call(self, name: str, arguments: dict) -> None:
        await self.emit(
            EventType.AGENT_TOOL_CALL,
            f"{name}({_short_args(arguments)})",
            stage="investigate",
            tool=name,
            arguments=arguments,
        )

    async def _on_tool_result(self, name: str, arguments: dict, output: dict) -> None:
        from .tools import summarize_tool_result

        summary = summarize_tool_result(name, output)
        await self.emit(
            EventType.AGENT_TOOL_RESULT,
            f"{name} -> {summary}",
            level=EventLevel.ERROR if output.get("error") else EventLevel.INFO,
            stage="investigate",
            tool=name,
            summary=summary,
            ok=not output.get("error"),
        )

    async def _on_offline_step(self, name: str, arguments: dict, output: dict) -> None:
        await self._on_tool_call(name, arguments)
        await self._on_tool_result(name, arguments, output)


def _short_args(arguments: dict) -> str:
    parts = []
    for key, value in list(arguments.items())[:3]:
        text = str(value)
        if len(text) > 60:
            text = text[:57] + "..."
        parts.append(f"{key}={text}")
    return ", ".join(parts)
