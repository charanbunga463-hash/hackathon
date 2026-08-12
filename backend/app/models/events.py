"""Agent activity events streamed to the UI over SSE."""

from __future__ import annotations

import itertools
from enum import Enum

from pydantic import BaseModel, Field

from ..utils.timestamps import utcnow_iso

_counter = itertools.count(1)


class EventLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    DEBUG = "debug"


class EventType(str, Enum):
    # lifecycle
    SESSION_STARTED = "session.started"
    SESSION_FINISHED = "session.finished"
    STAGE_STARTED = "stage.started"
    STAGE_FINISHED = "stage.finished"
    # project
    PROJECT_CREATED = "project.created"
    PROJECT_ANALYZED = "project.analyzed"
    PROJECT_DELETED = "project.deleted"
    # detection
    EXECUTION_STARTED = "execution.started"
    EXECUTION_FINISHED = "execution.finished"
    FAILURE_DETECTED = "failure.detected"
    NO_FAILURES = "failure.none"
    # agent
    AGENT_THINKING = "agent.thinking"
    AGENT_TOOL_CALL = "agent.tool_call"
    AGENT_TOOL_RESULT = "agent.tool_result"
    AGENT_MESSAGE = "agent.message"
    # diagnosis / patch
    DIAGNOSIS_READY = "diagnosis.ready"
    PLAN_READY = "plan.ready"
    PATCH_PROPOSED = "patch.proposed"
    PATCH_VALIDATED = "patch.validated"
    PATCH_REJECTED = "patch.rejected"
    AWAITING_APPROVAL = "patch.awaiting_approval"
    PATCH_APPLIED = "patch.applied"
    PATCH_ROLLED_BACK = "patch.rolled_back"
    # verification
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_PASSED = "verification.passed"
    VERIFICATION_FAILED = "verification.failed"
    RETRY_SCHEDULED = "retry.scheduled"
    # misc
    WARNING = "warning"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


class AgentEvent(BaseModel):
    id: int = Field(default_factory=lambda: next(_counter))
    type: EventType
    level: EventLevel = EventLevel.INFO
    message: str
    at: str = Field(default_factory=utcnow_iso)
    # Who this event belongs to. Stamped by the bus from the ambient request or
    # job context. An event about a project carries file paths, error text and
    # patch content, so the stream is filtered on it: `None` means "system
    # notice, safe for anyone", and anything project-scoped without a tenant is
    # dropped rather than broadcast.
    tenant: str | None = None
    project_id: str | None = None
    session_id: str | None = None
    stage: str | None = None
    attempt: int | None = None
    data: dict = Field(default_factory=dict)

    def visible_to(self, tenant: str | None) -> bool:
        if self.tenant is not None:
            return self.tenant == tenant
        # No owner recorded: only a genuinely global notice may pass.
        return self.project_id is None and self.session_id is None

    def to_sse(self) -> str:
        # `tenant` is an internal routing field; it never goes over the wire.
        payload = self.model_dump_json(exclude={"tenant"})
        return f"event: {self.type.value}\ndata: {payload}\n\n"
