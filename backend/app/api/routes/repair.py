"""Repair: start a session, approve or reject a patch, roll back, inspect state."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from ...config.settings import Settings
from ...models.execution import RunMode
from ...models.patch import PatchDecisionRequest
from ...models.report import RepairSession, RepairSessionSummary
from ...models.user import UserPreferences
from ...runtime.concurrency import io_bound
from ...runtime.identity import Principal
from ...runtime.jobs import JobConflict, JobRejected
from ...services.project_service import ProjectService
from ...services.repair_service import RepairError, RepairService
from ..deps import (
    current_principal,
    owned_project,
    project_service,
    repair_service,
    settings_dep,
)

router = APIRouter(prefix="/repair", tags=["repair"])


async def _preferences(
    principal: Principal, settings: Settings
) -> UserPreferences | None:
    """This caller's saved preferences, or None when they are not an account.

    A cache hit in the normal case: resolving the principal for this request
    already loaded the record.
    """
    if not principal.user_id:
        return None
    from ...services.user_service import get_user_service

    user = await get_user_service(settings).get_cached_async(principal.user_id)
    return user.preferences if user else None


class StartRepairRequest(BaseModel):
    mode: RunMode = RunMode.TEST
    failure_id: str | None = None
    auto_approve: bool | None = None


@router.post("/{project_id}/start")
async def start_repair(
    project_id: str,
    payload: StartRepairRequest,
    response: Response,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
    settings: Settings = Depends(settings_dep),
):
    """Start a repair. Returns immediately; follow progress on /api/events.

    Returns the session when the repair has started, or 202 with a job id when
    it is waiting for a slot.
    """
    await owned_project(project_id, projects, principal.tenant)
    preferences = await _preferences(principal, settings)

    # An explicit `auto_approve` in the request wins; otherwise the account's
    # saved preference decides, and only then the deployment default.
    auto_approve = payload.auto_approve
    if auto_approve is None and preferences is not None:
        auto_approve = not preferences.require_patch_approval

    try:
        job, session = await repairs.start_repair(
            project_id,
            mode=payload.mode,
            failure_id=payload.failure_id,
            auto_approve=auto_approve,
            tenant=principal.tenant,
            use_ai=preferences.ai_analysis if preferences is not None else True,
        )
        if session is None:
            response.status_code = status.HTTP_202_ACCEPTED
            queue = repairs.queue.stats()
            return {
                "queued": True,
                "job_id": job.id,
                "status_url": f"/api/execution/jobs/{job.id}",
                "queue_position": job.queue_position,
                "queue_depth": queue["queued"],
                "detail": "The repair is queued behind other work and will start shortly.",
            }
        return session.model_dump(mode="json")
    except JobRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except (JobConflict, RepairError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get("/{project_id}/active")
async def active_repair(
    project_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
):
    await owned_project(project_id, projects, principal.tenant)
    # Resolved across workers: a repair running anywhere outranks the newest
    # session on disk, so this answer does not depend on which worker replies.
    running, session = await repairs.active_snapshot(project_id, tenant=principal.tenant)
    return {
        "project_id": project_id,
        "running": running,
        "session": session.model_dump(mode="json") if session else None,
    }


@router.post("/{project_id}/patch/{patch_id}/decision")
async def decide_patch(
    project_id: str,
    patch_id: str,
    payload: PatchDecisionRequest,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
):
    """Developer approval gate. A patch is never applied without passing here."""
    await owned_project(project_id, projects, principal.tenant)
    try:
        await repairs.decide(project_id, patch_id, payload.approve, payload.note)
    except RepairError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {
        "project_id": project_id,
        "patch_id": patch_id,
        "approved": payload.approve,
        "note": payload.note,
    }


@router.post("/{project_id}/cancel")
async def cancel_repair(
    project_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
):
    await owned_project(project_id, projects, principal.tenant)
    cancelled = await repairs.cancel(project_id)
    return {"project_id": project_id, "cancelled": cancelled}


@router.get("/{project_id}/sessions", response_model=list[RepairSessionSummary])
async def list_sessions(
    project_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
):
    await owned_project(project_id, projects, principal.tenant)
    return await repairs.list_session_summaries_async(project_id, tenant=principal.tenant)


@router.get("/{project_id}/sessions/{session_id}", response_model=RepairSession)
async def get_session(
    project_id: str,
    session_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
):
    await owned_project(project_id, projects, principal.tenant)
    session = await repairs.load_session_async(project_id, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return session


@router.post("/{project_id}/sessions/{session_id}/rollback")
async def rollback_session(
    project_id: str,
    session_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
):
    """Undo an applied patch after the fact."""
    await owned_project(project_id, projects, principal.tenant)
    try:
        return await io_bound(repairs.rollback_session, project_id, session_id)
    except RepairError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{project_id}/snapshots")
async def list_snapshots(
    project_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
):
    from ...patches.snapshot_manager import SnapshotManager

    await owned_project(project_id, projects, principal.tenant)
    manager = SnapshotManager(
        projects.workspace(project_id), projects.snapshots_dir(project_id), project_id
    )
    snapshots = await io_bound(manager.list_snapshots)
    return [snapshot.model_dump(mode="json") for snapshot in snapshots]


@router.post("/{project_id}/snapshots/{snapshot_id}/restore")
async def restore_snapshot(
    project_id: str,
    snapshot_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
):
    from ...patches.snapshot_manager import SnapshotManager

    await owned_project(project_id, projects, principal.tenant)
    manager = SnapshotManager(
        projects.workspace(project_id), projects.snapshots_dir(project_id), project_id
    )
    ok, restored, errors = await io_bound(manager.restore, snapshot_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="; ".join(errors) or "restore failed"
        )
    return {"restored": restored, "snapshot_id": snapshot_id}
