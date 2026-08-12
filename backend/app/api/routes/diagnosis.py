"""Diagnosis: list detected failures and diagnose one without repairing it."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ...agents import diagnostician, investigator, offline_engine
from ...agents.tools import ToolContext
from ...ai.openai_client import (
    AIError,
    StructuredOutputError,
    get_openai_client,
)
from ...config.settings import Settings
from ...models.diagnosis import DiagnosisResult, Investigation
from ...models.execution import NormalizedFailure, RunMode
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

router = APIRouter(prefix="/diagnosis", tags=["diagnosis"])


class DiagnoseRequest(BaseModel):
    failure_id: str | None = None


class DiagnoseResponse(BaseModel):
    project_id: str
    failure: NormalizedFailure
    diagnosis: DiagnosisResult
    investigation: Investigation | None = None
    observed_facts: list[str] = []
    reasoning_engine: str = "openai"
    note: str = ""


@router.get("/{project_id}/failures", response_model=list[NormalizedFailure])
async def list_failures(
    project_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
):
    """Failures from the most recent execution of this project."""
    await owned_project(project_id, projects, principal.tenant)
    record = await repairs.latest_execution_async(project_id)
    if record is None:
        return []
    return record.failures()


@router.post("/{project_id}", response_model=DiagnoseResponse)
async def diagnose(
    project_id: str,
    payload: DiagnoseRequest,
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(settings_dep),
    projects: ProjectService = Depends(project_service),
    repairs: RepairService = Depends(repair_service),
):
    """Investigate and diagnose a failure. Read-only: nothing is patched."""
    await owned_project(project_id, projects, principal.tenant)
    project = await projects.ensure_analyzed_async(project_id, principal.tenant)

    record = await repairs.latest_execution_async(project_id)
    if record is None:
        # Nothing has been run yet. Detecting failures means starting a sandbox,
        # so it goes through admission control like any other heavy job.
        try:
            _job, future = await repairs.submit_execution(
                project_id, RunMode.TEST, tenant=principal.tenant
            )
            record = await future
        except JobRejected as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(exc),
                headers={"Retry-After": str(exc.retry_after)},
            ) from exc
        except JobConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    failures = record.failures()
    if not failures:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no failures were detected in the latest run; there is nothing to diagnose",
        )
    failure = next((f for f in failures if f.id == payload.failure_id), failures[0])

    sandbox = await repairs.sandbox()
    ctx = ToolContext(
        workspace=projects.workspace(project_id),
        metadata=project.metadata,
        settings=settings,
        sandbox=sandbox,
        failure=failure,
        openapi=(record.api_result.openapi if record.api_result else None),
        baseline=record.test_result,
    )

    client = get_openai_client(settings)
    note = ""
    if client.configured:
        try:
            investigation, ai_diagnosis = await investigator.investigate_with_ai(
                client, ctx, failure, test_run=record.test_result
            )
            diagnosis = diagnostician.from_ai(
                ctx.workspace, project.metadata, failure, ai_diagnosis
            )
            return DiagnoseResponse(
                project_id=project_id,
                failure=failure,
                diagnosis=diagnosis,
                investigation=investigation,
                observed_facts=diagnostician.observed_facts(failure, diagnosis),
                reasoning_engine="openai",
            )
        except (AIError, StructuredOutputError) as exc:
            note = f"AI diagnosis failed ({exc}); fell back to the deterministic engine."

    investigation = await investigator.investigate_offline(ctx, failure)
    diagnosis, _outcome = offline_engine.diagnose(ctx.workspace, project.metadata, failure)
    return DiagnoseResponse(
        project_id=project_id,
        failure=failure,
        diagnosis=diagnosis,
        investigation=investigation,
        observed_facts=diagnostician.observed_facts(failure, diagnosis),
        reasoning_engine=offline_engine.ENGINE_NAME,
        note=note
        or (
            "OPENAI_API_KEY is not configured, so this diagnosis came from the deterministic "
            "rule engine rather than a model."
        ),
    )
