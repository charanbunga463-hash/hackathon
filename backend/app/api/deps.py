"""Shared FastAPI dependencies.

The important one is `current_principal`: every route that touches project data
resolves a tenant here, and passes it into the service layer. Forgetting it is
a cross-tenant data leak, so `owned_project` is the only sanctioned way for a
route to load a project.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status

from ..config.settings import Settings, get_settings
from ..runtime.identity import ANONYMOUS_TENANT, Principal
from ..runtime.jobs import JobQueue, get_job_queue
from ..services.event_service import EventBus, get_event_bus
from ..services.project_service import (
    ProjectAccessError,
    ProjectError,
    ProjectQuotaError,
    ProjectService,
)
from ..services.repair_service import RepairService, get_repair_service
from ..services.report_service import ReportService


def settings_dep() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def _project_service() -> ProjectService:
    return ProjectService(get_settings())


def project_service(settings: Settings = Depends(settings_dep)) -> ProjectService:
    return _project_service()


def repair_service(
    settings: Settings = Depends(settings_dep),
    projects: ProjectService = Depends(project_service),
) -> RepairService:
    return get_repair_service(settings, projects)


def report_service(
    settings: Settings = Depends(settings_dep),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
) -> ReportService:
    return ReportService(settings, projects, repairs)


def event_bus() -> EventBus:
    return get_event_bus()


def job_queue() -> JobQueue:
    return get_job_queue()


def current_principal(request: Request) -> Principal:
    """The authenticated caller, resolved by middleware."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        # Middleware always sets this; if it did not, fail closed rather than
        # silently serving the request as the shared public tenant.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthenticated request"
        )
    return principal


def current_tenant(principal: Principal = Depends(current_principal)) -> str:
    return principal.tenant


async def owned_project(
    project_id: str,
    projects: ProjectService,
    tenant: str,
):
    """Load a project the caller owns, or 404.

    Missing and not-yours deliberately return the same status so project ids
    cannot be enumerated.
    """
    from ..runtime.concurrency import io_bound

    try:
        return await io_bound(projects.owned, project_id, tenant)
    except ProjectError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def require_project(project_id: str, projects: ProjectService, tenant: str | None = None):
    """Synchronous ownership check for the few call sites already off the loop."""
    try:
        return projects.owned(project_id, tenant)
    except ProjectError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def quota_error(exc: ProjectQuotaError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))


__all__ = [
    "ANONYMOUS_TENANT",
    "ProjectAccessError",
    "current_principal",
    "current_tenant",
    "event_bus",
    "job_queue",
    "owned_project",
    "project_service",
    "quota_error",
    "repair_service",
    "report_service",
    "require_project",
    "settings_dep",
]
