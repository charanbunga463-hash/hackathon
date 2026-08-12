"""Execution + failure-detection models."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..utils.timestamps import utcnow_iso


class RunMode(str, Enum):
    TEST = "test"
    API = "api"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StackFrame(BaseModel):
    file: str
    line: int
    function: str | None = None
    code: str | None = None
    in_project: bool = True


class NormalizedFailure(BaseModel):
    """One failure, normalised into the shape the agent reasons about."""

    id: str
    error_type: str = "UnknownError"
    message: str = ""
    file: str | None = None
    line: int | None = None
    function: str | None = None
    test: str | None = None
    endpoint: str | None = None
    status_code: int | None = None
    traceback: str = ""
    frames: list[StackFrame] = Field(default_factory=list)
    severity: Severity = Severity.HIGH
    source: Literal["pytest", "api_probe", "startup", "collection"] = "pytest"
    detected_at: str = Field(default_factory=utcnow_iso)
    raw_output: str = ""

    def headline(self) -> str:
        location = f" at {self.file}:{self.line}" if self.file and self.line else ""
        subject = self.endpoint or self.test or "project"
        return f"{subject} -> {self.error_type}: {self.message}{location}"


class TestCaseResult(BaseModel):
    node_id: str
    outcome: Literal["passed", "failed", "error", "skipped", "xfailed", "xpassed"]
    duration_ms: int = 0
    message: str = ""


class TestRunResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    exit_code: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    total: int = 0
    duration_ms: int = 0
    stdout: str = ""
    stderr: str = ""
    command: list[str] = Field(default_factory=list)
    runner: Literal["docker", "local"] = "local"
    timed_out: bool = False
    collection_error: str | None = None
    cases: list[TestCaseResult] = Field(default_factory=list)
    failures: list[NormalizedFailure] = Field(default_factory=list)
    started_at: str = Field(default_factory=utcnow_iso)

    @property
    def all_passed(self) -> bool:
        return (
            self.exit_code == 0
            and self.failed == 0
            and self.errors == 0
            and not self.timed_out
            and self.collection_error is None
        )

    def summary_line(self) -> str:
        if self.collection_error:
            return f"collection error: {self.collection_error.splitlines()[0][:160]}"
        if self.timed_out:
            return f"timed out after {self.duration_ms} ms"
        return (
            f"{self.passed}/{self.total} passed, {self.failed} failed, "
            f"{self.errors} errors in {self.duration_ms} ms"
        )


class EndpointProbeResult(BaseModel):
    method: str
    path: str
    url: str
    status_code: int | None = None
    ok: bool = False
    latency_ms: int = 0
    response_snippet: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class ApiRunResult(BaseModel):
    started: bool = False
    base_url: str | None = None
    startup_stdout: str = ""
    startup_stderr: str = ""
    startup_error: str | None = None
    openapi: dict | None = None
    probes: list[EndpointProbeResult] = Field(default_factory=list)
    failures: list[NormalizedFailure] = Field(default_factory=list)
    duration_ms: int = 0
    runner: Literal["docker", "local"] = "local"

    @property
    def all_ok(self) -> bool:
        return self.started and not self.failures


class ExecutionRecord(BaseModel):
    """One recorded execution of a project (test run or API probe sweep)."""

    id: str
    project_id: str
    mode: RunMode
    created_at: str = Field(default_factory=utcnow_iso)
    runner: Literal["docker", "local"] = "local"
    isolated: bool = False
    test_result: TestRunResult | None = None
    api_result: ApiRunResult | None = None
    failure_count: int = 0
    healthy: bool = False
    label: str = ""

    def failures(self) -> list[NormalizedFailure]:
        if self.test_result:
            return self.test_result.failures
        if self.api_result:
            return self.api_result.failures
        return []


class RunRequest(BaseModel):
    mode: RunMode = RunMode.TEST
    selector: str | None = None


class RunOptions(BaseModel):
    """Per-run knobs, resolved from the caller's saved preferences.

    Defaults here match `Settings`, so a caller that passes nothing behaves
    exactly as before this existed. See `models.user.UserPreferences` for where
    the values come from.
    """

    probe_timeout_seconds: float | None = None
    include_write_methods: bool = False

    @classmethod
    def from_preferences(cls, preferences) -> "RunOptions":
        if preferences is None:
            return cls()
        return cls(
            probe_timeout_seconds=float(preferences.api_timeout_seconds),
            include_write_methods=bool(preferences.probe_write_methods),
        )
