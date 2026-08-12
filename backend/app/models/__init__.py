"""Domain models for API Doctor."""

from .diagnosis import (
    AffectedFile,
    ClaimKind,
    DiagnosisResult,
    EvidenceItem,
    EvidenceKind,
    Hypothesis,
    Investigation,
    InvestigationStep,
    RepairPlan,
    RepairPlanStep,
)
from .events import AgentEvent, EventLevel, EventType
from .execution import (
    ApiRunResult,
    EndpointProbeResult,
    ExecutionRecord,
    NormalizedFailure,
    RunMode,
    RunRequest,
    Severity,
    StackFrame,
    TestCaseResult,
    TestRunResult,
)
from .patch import (
    AppliedPatch,
    EditOperation,
    FileEdit,
    FileSnapshot,
    PatchDecisionRequest,
    PatchProposal,
    PatchStatus,
    PatchValidation,
    Snapshot,
    ValidationIssue,
)
from .project import (
    DependencyInfo,
    FileContent,
    FileNode,
    Project,
    ProjectMetadata,
    ProjectSource,
    ProjectStats,
    ProjectStatus,
    ProjectSummary,
    RouteInfo,
    TestFileInfo,
)
from .report import (
    DashboardStats,
    InvestigationReport,
    RecentFailure,
    RepairAttempt,
    RepairSession,
    RepairSessionSummary,
    RepairStage,
    RepairVerdict,
    VerificationAnalysis,
)

__all__ = [name for name in dir() if not name.startswith("_")]
