"""pytest runner + result normalisation.

The test result is the ground truth of this product. `TestRunResult.all_passed`
is derived from the process exit code and parsed counts — never from anything a
language model said.
"""

from __future__ import annotations

from pathlib import Path

from ..analysis.log_analyzer import failures_from_pytest_output
from ..analysis.stacktrace_parser import (
    extract_collection_error,
    parse_counts,
    parse_short_summary,
)
from ..models.execution import TestCaseResult, TestRunResult
from ..security.execution_security import validate_test_selector
from ..utils.logging import get_logger
from .sandbox import Sandbox

logger = get_logger(__name__)

BASE_PYTEST_ARGS = [
    "-m", "pytest",
    "-p", "no:cacheprovider",
    "--maxfail=25",
    "-rf",          # short summary for failures
    "--tb=long",    # full tracebacks: the agent needs the frames
    "-q",
    "--color=no",
]


def build_pytest_args(selectors: list[str] | None = None) -> list[str]:
    args = list(BASE_PYTEST_ARGS)
    for selector in selectors or []:
        args.append(validate_test_selector(selector))
    return args


async def run_tests(
    sandbox: Sandbox,
    workspace: Path,
    *,
    selectors: list[str] | None = None,
    timeout: float | None = None,
) -> TestRunResult:
    """Run pytest in the workspace and normalise everything it printed."""
    args = build_pytest_args(selectors)
    result = await sandbox.run_python(args, workspace=workspace, timeout=timeout)

    stdout, stderr = result.stdout, result.stderr
    counts = parse_counts(stdout)
    short_summary = parse_short_summary(stdout)
    collection_error = None
    if result.exit_code not in (0, 1) or counts == {
        "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0, "xpassed": 0
    }:
        collection_error = extract_collection_error(stdout, stderr)

    cases = _cases_from_summary(short_summary, counts)
    failures = []
    if result.exit_code != 0 or counts["failed"] or counts["errors"] or collection_error:
        failures = failures_from_pytest_output(
            stdout, stderr, project_root=workspace, short_summary=short_summary
        )

    total = (
        counts["passed"] + counts["failed"] + counts["errors"]
        + counts["skipped"] + counts["xfailed"] + counts["xpassed"]
    )

    run = TestRunResult(
        exit_code=result.exit_code,
        passed=counts["passed"],
        failed=counts["failed"],
        errors=counts["errors"],
        skipped=counts["skipped"],
        total=total,
        duration_ms=result.duration_ms,
        stdout=stdout,
        stderr=stderr,
        command=result.command,
        runner=sandbox.kind,
        timed_out=result.timed_out,
        collection_error=collection_error,
        cases=cases,
        failures=failures,
    )
    logger.info("pytest [%s]: %s", sandbox.kind, run.summary_line())
    return run


def _cases_from_summary(short_summary: list[dict], counts: dict[str, int]) -> list[TestCaseResult]:
    cases = [
        TestCaseResult(
            node_id=entry["node_id"],
            outcome="failed" if entry["outcome"] == "failed" else "error",
            message=entry.get("detail", "")[:400],
        )
        for entry in short_summary
    ]
    # pytest -q does not list passing node ids; represent them as an aggregate.
    for index in range(counts.get("passed", 0)):
        cases.append(
            TestCaseResult(node_id=f"<passed #{index + 1}>", outcome="passed", message="")
        )
    return cases


def compare_runs(before: TestRunResult, after: TestRunResult) -> dict:
    """What actually changed between the pre-patch and post-patch runs."""
    before_failed = {c.node_id for c in before.cases if c.outcome in {"failed", "error"}}
    after_failed = {c.node_id for c in after.cases if c.outcome in {"failed", "error"}}
    fixed = sorted(before_failed - after_failed)
    still_failing = sorted(before_failed & after_failed)
    new_failures = sorted(after_failed - before_failed)
    return {
        "fixed": fixed,
        "still_failing": still_failing,
        "new_failures": new_failures,
        "regression": bool(new_failures),
        "passed_before": before.passed,
        "passed_after": after.passed,
        "failed_before": before.failed + before.errors,
        "failed_after": after.failed + after.errors,
    }
