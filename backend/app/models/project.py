"""Project + analysis domain models."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..utils.timestamps import utcnow_iso


class ProjectSource(str, Enum):
    UPLOAD = "upload"


class ProjectStatus(str, Enum):
    CREATED = "created"
    ANALYZING = "analyzing"
    READY = "ready"
    HEALTHY = "healthy"
    FAILING = "failing"
    REPAIRING = "repairing"
    REPAIRED = "repaired"
    ERROR = "error"


class RouteInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    method: str
    path: str
    file: str
    line: int = 0
    function: str | None = None
    source: Literal["static", "openapi"] = "static"
    status_codes: list[int] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)
    request_body: str | None = None
    response_model: str | None = None
    summary: str | None = None

    @property
    def signature(self) -> str:
        return f"{self.method.upper()} {self.path}"


class DependencyInfo(BaseModel):
    name: str
    specifier: str | None = None
    source_file: str = ""


class TestFileInfo(BaseModel):
    path: str
    test_count: int = 0
    test_names: list[str] = Field(default_factory=list)


class ProjectMetadata(BaseModel):
    """Everything static analysis learned about a workspace."""

    language: str = "unknown"
    framework: str = "unknown"
    entry_point: str | None = None
    app_object: str | None = None
    test_framework: str | None = None
    test_files: list[str] = Field(default_factory=list)
    test_details: list[TestFileInfo] = Field(default_factory=list)
    routes: list[RouteInfo] = Field(default_factory=list)
    dependencies: list[DependencyInfo] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    has_dockerfile: bool = False
    has_readme: bool = False
    openapi_available: bool = False
    file_count: int = 0
    total_size_bytes: int = 0
    python_version_hint: str | None = None
    notes: list[str] = Field(default_factory=list)
    analyzed_at: str | None = None

    def route_index(self) -> dict[str, RouteInfo]:
        return {route.signature: route for route in self.routes}


class ProjectStats(BaseModel):
    failures_detected: int = 0
    repairs_attempted: int = 0
    repairs_verified: int = 0
    last_run_at: str | None = None
    last_verdict: str | None = None


class Project(BaseModel):
    id: str
    name: str
    # Records written before the Demo Lab was removed carry source="demo".
    # Rejecting them would make a user's existing projects silently disappear
    # from their list, so an unknown source is read as an ordinary upload —
    # which is what those projects now are.
    source: ProjectSource
    # The tenant that owns this workspace. Every read and write is scoped by it,
    # so one user can never see or repair another user's code.
    owner: str = "public"
    status: ProjectStatus = ProjectStatus.CREATED
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    origin: str | None = None            # the uploaded filename
    description: str | None = None
    metadata: ProjectMetadata | None = None
    stats: ProjectStats = Field(default_factory=ProjectStats)
    upload_report: dict | None = None
    error: str | None = None

    @field_validator("source", mode="before")
    @classmethod
    def _accept_legacy_source(cls, value):
        if isinstance(value, str) and value not in {member.value for member in ProjectSource}:
            return ProjectSource.UPLOAD.value
        return value

    def touch(self) -> None:
        self.updated_at = utcnow_iso()


class ProjectSummary(BaseModel):
    """List-view projection; avoids shipping full metadata for every card."""

    id: str
    name: str
    source: ProjectSource
    owner: str = "public"
    status: ProjectStatus
    created_at: str
    updated_at: str
    origin: str | None = None
    language: str = "unknown"
    framework: str = "unknown"
    route_count: int = 0
    test_count: int = 0
    stats: ProjectStats = Field(default_factory=ProjectStats)

    @classmethod
    def from_project(cls, project: Project) -> "ProjectSummary":
        metadata = project.metadata
        return cls(
            id=project.id,
            name=project.name,
            source=project.source,
            owner=project.owner,
            status=project.status,
            created_at=project.created_at,
            updated_at=project.updated_at,
            origin=project.origin,
            language=metadata.language if metadata else "unknown",
            framework=metadata.framework if metadata else "unknown",
            route_count=len(metadata.routes) if metadata else 0,
            test_count=sum(t.test_count for t in metadata.test_details) if metadata else 0,
            stats=project.stats,
        )


class FileNode(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory"]
    size: int = 0
    children: list["FileNode"] | None = None


FileNode.model_rebuild()


class FileContent(BaseModel):
    path: str
    content: str
    lines: int
    size: int
    truncated: bool = False
    language: str = "plaintext"


