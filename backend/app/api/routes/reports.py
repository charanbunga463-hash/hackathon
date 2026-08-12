"""Dashboard aggregates, repair history and investigation reports.

All three scan session files, so every handler here runs its work in a thread.
The dashboard is the most-polled endpoint in the product; leaving it on the
event loop was the difference between 40 and 900 requests/second under load.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ...models.report import InvestigationReport
from ...runtime.identity import Principal
from ...services.repair_service import RepairService
from ...services.report_service import ReportService
from ..deps import current_principal, repair_service, report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/dashboard")
async def dashboard(
    principal: Principal = Depends(current_principal),
    reports: ReportService = Depends(report_service),
) -> dict:
    return await reports.dashboard_async(principal.tenant)


@router.get("/history")
async def history(
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(current_principal),
    reports: ReportService = Depends(report_service),
) -> dict:
    return {"entries": await reports.history_async(limit=limit, tenant=principal.tenant)}


@router.get("/sessions/{session_id}", response_model=InvestigationReport)
async def session_report(
    session_id: str,
    principal: Principal = Depends(current_principal),
    repairs: RepairService = Depends(repair_service),
    reports: ReportService = Depends(report_service),
):
    found = await repairs.find_session_async(session_id, principal.tenant)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    _project_id, session = found
    return await reports.build_report_async(session)


@router.get("/sessions/{session_id}/markdown")
async def session_report_markdown(
    session_id: str,
    principal: Principal = Depends(current_principal),
    repairs: RepairService = Depends(repair_service),
    reports: ReportService = Depends(report_service),
):
    found = await repairs.find_session_async(session_id, principal.tenant)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    _project_id, session = found
    report = await reports.build_report_async(session)
    return Response(
        content=report.markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="api-doctor-{session_id}.md"'
        },
    )
