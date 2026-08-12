"""Execution: run tests, probe the API, inspect the sandbox.

Runs go through the job queue. Under load the honest answer to "run my tests" is
often "you are third in line", not a request that hangs for four minutes and
then times out behind a proxy.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ...config.settings import Settings
from ...execution.sandbox import probe_execution_state
from ...models.execution import ExecutionRecord, RunMode, RunOptions, RunRequest
from ...runtime.identity import Principal
from ...runtime.jobs import JobConflict, JobRejected
from ...services.project_service import ProjectService
from ...services.repair_service import RepairService
from ..deps import (
    current_principal,
    owned_project,
    project_service,
    repair_service,
    settings_dep,
)

router = APIRouter(prefix="/execution", tags=["execution"])

# How long to hold the connection before handing back a job id instead.
#
# Deliberately short. A typical demo test run finishes in 3-4 s, so this still
# answers the common case inline — but under queueing a longer wait stacks on
# top of queue time and overruns the client's own timeout, turning a working
# 202 into a failed request. Load testing at 300 concurrent users produced
# exactly that: a 25 s wait plus queueing tripped a 30 s client timeout.
INLINE_WAIT_SECONDS = 8.0


@router.get("/sandbox")
async def sandbox_info(settings: Settings = Depends(settings_dep)) -> dict:
    """The execution posture, probed. Shares the cached probe with /api/system."""
    state = await probe_execution_state(settings)
    capabilities = state["sandbox"]
    if capabilities.get("error"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=capabilities["error"]
        )
    isolated = bool(state["execution_isolated"])
    return {
        **capabilities,
        "configured_mode": settings.execution_mode,
        "docker_cli_present": settings.docker_available,
        "docker_daemon_reachable": state["execution_mode_resolved"] == "docker",
        "trusted_mode_banner": (
            None
            if isolated
            else "LOCAL TRUSTED MODE — uploaded code runs on the host without isolation."
        ),
    }


@router.get("/queue")
async def queue_status(repairs: RepairService = Depends(repair_service)) -> dict:
    """Live capacity, so a client can show 'N ahead of you' instead of a spinner."""
    return repairs.queue.stats()


@router.get("/jobs/{job_id:path}")
async def job_status(
    job_id: str,
    principal: Principal = Depends(current_principal),
    repairs: RepairService = Depends(repair_service),
) -> dict:
    record = await repairs.queue.get(job_id)
    if record is None or record.tenant != principal.tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return record.as_dict()


async def _resolve_options(principal: Principal, settings: Settings) -> RunOptions:
    """Turn the caller's saved preferences into per-run options.

    A cache hit in the common case — resolving this request's principal loaded
    the same record a moment ago — so this does not add a read to the path.
    Anything other than a user session (API keys, open mode) has no preferences
    and gets the deployment defaults.
    """
    if not principal.user_id:
        return RunOptions()
    from ...services.user_service import get_user_service

    user = await get_user_service(settings).get_cached_async(principal.user_id)
    return RunOptions.from_preferences(user.preferences if user else None)


async def _run_or_queue(
    project_id: str,
    mode: RunMode,
    principal: Principal,
    projects: ProjectService,
    repairs: RepairService,
    response: Response,
    settings: Settings,
):
    await owned_project(project_id, projects, principal.tenant)
    options = await _resolve_options(principal, settings)
    try:
        job, future = await repairs.submit_execution(
            project_id, mode, tenant=principal.tenant, options=options
        )
    except JobRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except JobConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    try:
        # Wait briefly so the common case still feels synchronous...
        record = await asyncio.wait_for(asyncio.shield(future), timeout=INLINE_WAIT_SECONDS)
    except asyncio.TimeoutError:
        # ...and hand back a job id when it is genuinely slow. `shield` keeps the
        # job running: the client's patience expiring must not cancel real work.
        response.status_code = status.HTTP_202_ACCEPTED
        return {
            "queued": True,
            "job_id": job.id,
            "status_url": f"/api/execution/jobs/{job.id}",
            "detail": (
                "The run is still in progress. Poll status_url, or follow /api/events "
                "for live progress."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return record


@router.post("/{project_id}/run")
async def run_project(
    project_id: str,
    payload: RunRequest,
    response: Response,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
    settings: Settings = Depends(settings_dep),
):
    return await _run_or_queue(
        project_id, payload.mode, principal, projects, repairs, response, settings
    )


@router.post("/{project_id}/tests")
async def run_tests_endpoint(
    project_id: str,
    response: Response,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
    settings: Settings = Depends(settings_dep),
):
    return await _run_or_queue(
        project_id, RunMode.TEST, principal, projects, repairs, response, settings
    )


@router.post("/{project_id}/probe")
async def probe_api(
    project_id: str,
    response: Response,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
    settings: Settings = Depends(settings_dep),
):
    return await _run_or_queue(
        project_id, RunMode.API, principal, projects, repairs, response, settings
    )


@router.get("/{project_id}/history", response_model=list[ExecutionRecord])
async def execution_history(
    project_id: str,
    limit: int = 20,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
):
    await owned_project(project_id, projects, principal.tenant)
    return await repairs.list_executions_async(project_id, limit=min(limit, 100))


@router.get("/{project_id}/latest")
async def latest_execution(
    project_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
):
    await owned_project(project_id, projects, principal.tenant)
    record = await repairs.latest_execution_async(project_id)
    if record is None:
        return {"project_id": project_id, "record": None}
    return {"project_id": project_id, "record": record.model_dump(mode="json")}
