"""Patch models.

A patch is a list of *anchored replacements*: `old` text that must appear
exactly once in the target file, replaced by `new`. This is deliberately not a
free-form unified diff — an anchored replacement is trivially verifiable
against the real file before anything is written, which is what makes
"apply safely" a real guarantee rather than a hope.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

from ..utils.timestamps import utcnow_iso


class PatchStatus(str, Enum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    REJECTED = "rejected"
    AWAITING_APPROVAL = "awaiting_approval"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


class EditOperation(str, Enum):
    REPLACE = "replace"
    INSERT_AFTER = "insert_after"
    CREATE_FILE = "create_file"


class FileEdit(BaseModel):
    path: str
    operation: EditOperation = EditOperation.REPLACE
    old: str = ""
    new: str = ""
    line_hint: int | None = None
    reason: str = ""

    @field_validator("path")
    @classmethod
    def _path_present(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("edit path is required")
        return cleaned


class PatchProposal(BaseModel):
    id: str
    project_id: str
    failure_id: str | None = None
    attempt: int = 1
    title: str = ""
    explanation: str = ""
    edits: list[FileEdit] = Field(default_factory=list)
    tests_to_run: list[str] = Field(default_factory=list)
    risk: str = "low"
    confidence: float = 0.0
    status: PatchStatus = PatchStatus.PROPOSED
    reasoning_engine: str = "openai"
    created_at: str = Field(default_factory=utcnow_iso)
    diff: str = ""
    stats: dict = Field(default_factory=dict)

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class ValidationIssue(BaseModel):
    severity: str = "error"       # error | warning
    code: str
    message: str
    path: str | None = None


class PatchValidation(BaseModel):
    valid: bool = False
    issues: list[ValidationIssue] = Field(default_factory=list)
    files_touched: list[str] = Field(default_factory=list)
    lines_added: int = 0
    lines_removed: int = 0
    syntax_checked: list[str] = Field(default_factory=list)
    diff: str = ""
    checked_at: str = Field(default_factory=utcnow_iso)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]


class FileSnapshot(BaseModel):
    path: str
    existed: bool
    sha256: str | None = None
    stored_as: str | None = None


class Snapshot(BaseModel):
    id: str
    project_id: str
    patch_id: str | None = None
    created_at: str = Field(default_factory=utcnow_iso)
    files: list[FileSnapshot] = Field(default_factory=list)
    label: str = ""
    restored: bool = False


class AppliedPatch(BaseModel):
    patch_id: str
    snapshot_id: str
    applied_at: str = Field(default_factory=utcnow_iso)
    files_changed: list[str] = Field(default_factory=list)
    diff: str = ""
    rolled_back: bool = False
    rolled_back_at: str | None = None
    rollback_reason: str | None = None


class PatchDecisionRequest(BaseModel):
    approve: bool
    note: str | None = None
