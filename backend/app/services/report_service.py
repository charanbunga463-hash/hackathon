"""Investigation reports and dashboard aggregates.

The report is the product's final artefact. It is structured around the claim
ladder — OBSERVED FACT, HYPOTHESIS, ROOT CAUSE, PROPOSED FIX, TEST RESULT,
VERIFIED RESULT — and the headline is derived from the measured verdict, never
from prose.
"""

from __future__ import annotations

from ..config.settings import Settings
from ..models.report import (
    DashboardStats,
    InvestigationReport,
    RecentFailure,
    RepairSession,
    RepairVerdict,
)
from ..utils.timestamps import utcnow_iso
from .project_service import ProjectService
from .repair_service import RepairService

VERDICT_HEADLINE = {
    RepairVerdict.VERIFIED: "FIX VERIFIED",
    RepairVerdict.REPAIR_FAILED: "REPAIR FAILED",
    RepairVerdict.PATCH_APPLIED_UNVERIFIED: "PATCH APPLIED — NOT VERIFIED",
    RepairVerdict.AWAITING_APPROVAL: "AWAITING DEVELOPER APPROVAL",
    RepairVerdict.REJECTED_BY_DEVELOPER: "PATCH REJECTED BY DEVELOPER",
    RepairVerdict.NO_FAILURE_DETECTED: "NO FAILURE DETECTED",
    RepairVerdict.ABORTED: "STOPPED SAFELY — NO CHANGES APPLIED",
    RepairVerdict.ERROR: "RUN FAILED",
    RepairVerdict.PENDING: "IN PROGRESS",
}

DISCLAIMER_VERIFIED = (
    "This verdict was produced by running the project's own test suite after the patch "
    "was applied. The pass/fail result is measured, not inferred."
)
DISCLAIMER_UNVERIFIED = (
    "No repair has been verified. Any root cause and patch shown here are proposals "
    "supported by the listed evidence; they have not been proven to fix the failure."
)


class ReportService:
    def __init__(self, settings: Settings, projects: ProjectService, repairs: RepairService) -> None:
        self.settings = settings
        self.projects = projects
        self.repairs = repairs

    # ------------------------------------------------------------ report --
    def build_report(self, session: RepairSession) -> InvestigationReport:
        from ..agents.diagnostician import observed_facts

        last = session.attempts[-1] if session.attempts else None
        diagnosis = last.diagnosis if last else None
        patch = last.patch if last else None
        verification = last.verification if last else None

        facts: list[str] = []
        if session.target_failure and diagnosis:
            facts = observed_facts(session.target_failure, diagnosis)
        elif session.target_failure:
            failure = session.target_failure
            if failure.endpoint and failure.status_code:
                facts.append(f"{failure.endpoint} returned HTTP {failure.status_code}.")
            if failure.test:
                facts.append(f"{failure.test} failed.")
            if failure.error_type:
                facts.append(f"{failure.error_type}: {failure.message}")
        if session.baseline:
            facts.insert(0, f"Baseline test run: {session.baseline.summary_line()}.")

        hypotheses = []
        if diagnosis:
            for hypothesis in diagnosis.hypotheses:
                marker = {"supported": "SUPPORTED", "rejected": "REJECTED", "open": "OPEN"}.get(
                    hypothesis.status, "OPEN"
                )
                hypotheses.append(f"[{marker}] {hypothesis.statement}")

        test_results = []
        for attempt in session.attempts:
            if attempt.targeted_test:
                test_results.append(
                    {
                        "attempt": attempt.attempt,
                        "scope": "targeted",
                        "summary": attempt.targeted_test.summary_line(),
                        "passed": attempt.targeted_test.passed,
                        "failed": attempt.targeted_test.failed + attempt.targeted_test.errors,
                        "total": attempt.targeted_test.total,
                        "exit_code": attempt.targeted_test.exit_code,
                    }
                )
            if attempt.full_test:
                test_results.append(
                    {
                        "attempt": attempt.attempt,
                        "scope": "full",
                        "summary": attempt.full_test.summary_line(),
                        "passed": attempt.full_test.passed,
                        "failed": attempt.full_test.failed + attempt.full_test.errors,
                        "total": attempt.full_test.total,
                        "exit_code": attempt.full_test.exit_code,
                    }
                )

        report = InvestigationReport(
            session_id=session.id,
            project_id=session.project_id,
            project_name=session.project_name,
            verdict=session.verdict,
            verified=session.verified,
            headline=VERDICT_HEADLINE.get(session.verdict, session.verdict.value.upper()),
            observed_facts=facts,
            hypotheses=hypotheses,
            root_cause=diagnosis.root_cause if diagnosis else None,
            evidence=[
                {
                    "kind": item.kind.value,
                    "source": item.source,
                    "line": item.line,
                    "detail": item.detail,
                    "excerpt": item.excerpt,
                    "verified": item.verified,
                }
                for item in (diagnosis.evidence if diagnosis else [])
            ],
            proposed_fix=(f"{patch.title} — {patch.explanation}" if patch else None),
            diff=(patch.diff if patch and patch.diff else None),
            test_results=test_results,
            verification=(verification.model_dump(mode="json") if verification else None),
            timeline=self._timeline(session),
            attempts=len(session.attempts),
            reasoning_engine=session.reasoning_engine,
            execution_runner=session.execution_runner,
            isolated_execution=session.isolated_execution,
            disclaimer=DISCLAIMER_VERIFIED if session.verified else DISCLAIMER_UNVERIFIED,
        )
        report.markdown = self.to_markdown(report, session)
        return report

    def _timeline(self, session: RepairSession) -> list[dict]:
        entries: list[dict] = [
            {"at": session.created_at, "stage": "observe", "detail": "Repair session started"}
        ]
        if session.baseline:
            entries.append(
                {
                    "at": session.baseline.started_at,
                    "stage": "observe",
                    "detail": f"Baseline: {session.baseline.summary_line()}",
                }
            )
        if session.target_failure:
            entries.append(
                {
                    "at": session.target_failure.detected_at,
                    "stage": "observe",
                    "detail": f"Failure selected: {session.target_failure.headline()}",
                }
            )
        for attempt in session.attempts:
            entries.append(
                {
                    "at": attempt.started_at,
                    "stage": "investigate",
                    "detail": f"Attempt {attempt.attempt} started",
                }
            )
            if attempt.investigation:
                entries.append(
                    {
                        "at": attempt.investigation.finished_at or attempt.started_at,
                        "stage": "investigate",
                        "detail": (
                            f"{len(attempt.investigation.steps)} investigation step(s), "
                            f"{len(attempt.investigation.files_read)} file(s) read"
                        ),
                    }
                )
            if attempt.diagnosis:
                entries.append(
                    {
                        "at": attempt.diagnosis.created_at,
                        "stage": "diagnose",
                        "detail": f"Root cause (confidence {attempt.diagnosis.confidence:.0%})",
                    }
                )
            if attempt.patch:
                entries.append(
                    {
                        "at": attempt.patch.created_at,
                        "stage": "patch",
                        "detail": f"Patch proposed: {attempt.patch.title}",
                    }
                )
            if attempt.applied:
                entries.append(
                    {
                        "at": attempt.applied.applied_at,
                        "stage": "apply",
                        "detail": f"Applied to {', '.join(attempt.applied.files_changed)}",
                    }
                )
            if attempt.full_test:
                entries.append(
                    {
                        "at": attempt.full_test.started_at,
                        "stage": "verify",
                        "detail": f"Full suite: {attempt.full_test.summary_line()}",
                    }
                )
            if attempt.rolled_back:
                entries.append(
                    {
                        "at": attempt.finished_at or attempt.started_at,
                        "stage": "rollback",
                        "detail": "Workspace rolled back",
                    }
                )
            if attempt.finished_at:
                entries.append(
                    {
                        "at": attempt.finished_at,
                        "stage": "attempt",
                        "detail": f"Attempt {attempt.attempt}: {attempt.outcome}",
                    }
                )
        if session.finished_at:
            entries.append(
                {"at": session.finished_at, "stage": "done", "detail": session.summary}
            )
        return entries

    def to_markdown(self, report: InvestigationReport, session: RepairSession) -> str:
        lines: list[str] = [
            f"# API Doctor — Investigation Report",
            "",
            f"**{report.headline}**",
            "",
            f"- Project: `{report.project_name}`",
            f"- Session: `{report.session_id}`",
            f"- Generated: {report.generated_at}",
            f"- Reasoning engine: `{report.reasoning_engine}`",
            f"- Execution: `{report.execution_runner}` "
            f"({'isolated sandbox' if report.isolated_execution else 'LOCAL TRUSTED MODE — no isolation'})",
            f"- Attempts: {report.attempts}",
            "",
            "## Observed facts",
            "",
        ]
        lines += [f"- {fact}" for fact in report.observed_facts] or ["- (none recorded)"]

        if report.hypotheses:
            lines += ["", "## Hypotheses considered", ""]
            lines += [f"- {item}" for item in report.hypotheses]

        lines += ["", "## Root cause", ""]
        lines.append(report.root_cause or "_Not established._")

        if report.evidence:
            lines += ["", "## Evidence", ""]
            for item in report.evidence:
                location = f":{item['line']}" if item.get("line") else ""
                mark = "verified" if item.get("verified") else "unverified"
                lines.append(f"- `{item['source']}{location}` ({mark}) — {item['detail']}")
                if item.get("excerpt"):
                    lines += ["", "  ```", f"  {item['excerpt']}", "  ```", ""]

        if report.proposed_fix:
            lines += ["", "## Proposed fix", "", report.proposed_fix]
        if report.diff:
            lines += ["", "```diff", report.diff.rstrip(), "```"]

        if report.test_results:
            lines += ["", "## Test results", ""]
            for entry in report.test_results:
                lines.append(
                    f"- Attempt {entry['attempt']} ({entry['scope']}): {entry['summary']}"
                )

        lines += ["", "## Verdict", "", f"**{report.headline}**", ""]
        lines.append(session.summary or "")
        lines += ["", f"> {report.disclaimer}", ""]
        return "\n".join(lines)

    # -------------------------------------------------------- dashboard ---
    def dashboard_stats(self, tenant: str | None = None) -> DashboardStats:
        projects = self.projects.list_projects(tenant)
        sessions = self.repairs.list_sessions(limit=500, tenant=tenant)
        attempted = [
            session for session in sessions
            if session.verdict
            not in {RepairVerdict.NO_FAILURE_DETECTED, RepairVerdict.PENDING}
        ]
        verified = [session for session in sessions if session.verified]
        # Failures found by plain execution runs are counted on the project record;
        # failures found inside a repair session are counted on the session.
        failures_detected = max(
            sum(len(session.baseline_failures) for session in sessions),
            sum(summary.stats.failures_detected for summary in projects),
        )
        total_attempts = sum(len(session.attempts) for session in attempted)

        # Report the sandbox we have actually built, not the one configuration
        # hopes for. Before anything has run there is nothing to prove, so the
        # safe value stands.
        probed = self.repairs.sandbox_if_built()
        resolved_mode = probed.kind if probed else "not yet determined"
        isolated = bool(probed and probed.capabilities().isolated)
        return DashboardStats(
            projects=len(projects),
            failures_detected=failures_detected,
            repairs_attempted=len(attempted),
            repairs_verified=len(verified),
            repair_success_rate=(len(verified) / len(attempted)) if attempted else 0.0,
            average_repair_attempts=(total_attempts / len(attempted)) if attempted else 0.0,
            average_repair_seconds=(
                sum(s.duration_ms for s in attempted) / len(attempted) / 1000.0
                if attempted else 0.0
            ),
            sessions=len(sessions),
            reasoning_engine=(
                "openai" if self.settings.ai_enabled else "deterministic-offline"
            ),
            execution_mode=resolved_mode,
            isolated_execution=isolated,
        )

    def recent_failures(self, limit: int = 12, tenant: str | None = None) -> list[RecentFailure]:
        entries: list[RecentFailure] = []
        projects = {summary.id: summary for summary in self.projects.list_projects(tenant)}

        for session in self.repairs.list_sessions(limit=80, tenant=tenant):
            name = projects[session.project_id].name if session.project_id in projects else session.project_name
            for failure in session.baseline_failures:
                entries.append(
                    RecentFailure(
                        project_id=session.project_id,
                        project_name=name,
                        session_id=session.id,
                        endpoint=failure.endpoint,
                        test=failure.test,
                        error_type=failure.error_type,
                        message=failure.message[:200],
                        status_code=failure.status_code,
                        detected_at=failure.detected_at,
                        status=self._failure_status(session, failure.id),
                        verdict=session.verdict,
                    )
                )

        for project_id, summary in projects.items():
            record = self.repairs.latest_execution(project_id)
            if record is None:
                continue
            for failure in record.failures():
                if any(
                    entry.project_id == project_id
                    and entry.error_type == failure.error_type
                    and entry.message == failure.message[:200]
                    for entry in entries
                ):
                    continue
                entries.append(
                    RecentFailure(
                        project_id=project_id,
                        project_name=summary.name,
                        session_id=None,
                        endpoint=failure.endpoint,
                        test=failure.test,
                        error_type=failure.error_type,
                        message=failure.message[:200],
                        status_code=failure.status_code,
                        detected_at=failure.detected_at,
                        status="Repair Available",
                    )
                )

        entries.sort(key=lambda entry: entry.detected_at, reverse=True)
        return entries[:limit]

    def _failure_status(self, session: RepairSession, failure_id: str) -> str:
        if session.target_failure and session.target_failure.id == failure_id:
            return {
                RepairVerdict.VERIFIED: "Repaired — Verified",
                RepairVerdict.REPAIR_FAILED: "Repair Failed",
                RepairVerdict.AWAITING_APPROVAL: "Awaiting Approval",
                RepairVerdict.REJECTED_BY_DEVELOPER: "Patch Rejected",
                RepairVerdict.ABORTED: "Stopped Safely",
                RepairVerdict.ERROR: "Run Failed",
            }.get(session.verdict, "Repair Available")
        return "Repair Available"

    def history(self, limit: int = 100, tenant: str | None = None) -> list[dict]:
        entries = []
        for session in self.repairs.list_sessions(limit=limit, tenant=tenant):
            last = session.attempts[-1] if session.attempts else None
            entries.append(
                {
                    "session_id": session.id,
                    "project_id": session.project_id,
                    "project_name": session.project_name,
                    "created_at": session.created_at,
                    "finished_at": session.finished_at,
                    "verdict": session.verdict.value,
                    "verified": session.verified,
                    "attempts": len(session.attempts),
                    "target": session.target_failure.headline() if session.target_failure else None,
                    "root_cause": last.diagnosis.root_cause if last and last.diagnosis else None,
                    "patch_title": last.patch.title if last and last.patch else None,
                    "duration_ms": session.duration_ms,
                    "engine": session.reasoning_engine,
                    "summary": session.summary,
                }
            )
        return entries

    def system_info(self) -> dict:
        info = self.settings.public_system_info()
        info["generated_at"] = utcnow_iso()
        return info

    # -------------------------------------------------------------- async --
    async def dashboard_async(self, tenant: str | None = None) -> dict:
        """Build the dashboard off the event loop, once per TTL per tenant.

        This scans every session file, so it is both the most expensive and the
        most frequently polled endpoint. Single-flight means 1000 concurrent
        viewers cost one scan, not 1000.
        """
        from ..runtime.cache import get_cache
        from ..runtime.concurrency import io_bound

        def build() -> dict:
            return {
                "stats": self.dashboard_stats(tenant).model_dump(mode="json"),
                "recent_failures": [
                    failure.model_dump(mode="json")
                    for failure in self.recent_failures(tenant=tenant)
                ],
                "system": self.system_info(),
            }

        from ..runtime.shared_cache import cached

        # Two tiers: the in-process cache collapses concurrent polls, Redis
        # shares the result with every other worker hitting the same database.
        return await cached(
            f"dashboard:{tenant}",
            lambda: io_bound(build),
            ttl=self.settings.db_cache_ttl_seconds,
        )

    async def history_async(self, limit: int = 100, tenant: str | None = None) -> list[dict]:
        from ..runtime.concurrency import io_bound
        from ..runtime.shared_cache import cached

        return await cached(
            f"history:{tenant}:{limit}",
            lambda: io_bound(self.history, limit, tenant),
            ttl=self.settings.db_cache_ttl_seconds,
        )

    async def build_report_async(self, session) -> InvestigationReport:
        from ..runtime.concurrency import cpu_bound

        return await cpu_bound(self.build_report, session)
