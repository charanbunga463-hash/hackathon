"""Project management: upload, analyse, browse, delete.

Every handler is tenant-scoped and non-blocking. Two rules hold throughout:

  * a project is only ever loaded through `owned_project`, so a caller cannot
    read, analyse or delete another tenant's workspace;
  * no synchronous disk or CPU work runs inline, because blocking the event
    loop stalls every other request on this worker.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from ...config.settings import Settings
from ...models.events import EventType
from ...models.project import (
    FileContent,
    Project,
    ProjectSummary,
)
from ...runtime.concurrency import io_bound
from ...runtime.identity import Principal
from ...services.event_service import emit_simple
from ...services.project_service import ProjectError, ProjectQuotaError, ProjectService
from ..deps import (
    current_principal,
    owned_project,
    project_service,
    quota_error,
    settings_dep,
)

router = APIRouter(prefix="/projects", tags=["projects"])

UPLOAD_CHUNK = 1024 * 1024


@router.get("", response_model=list[ProjectSummary])
async def list_projects(
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
):
    return await projects.list_projects_async(principal.tenant)


@router.get("/usage")
async def project_usage(
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
):
    """What this tenant has consumed against its quota."""
    return await projects.usage_async(principal.tenant)


@router.post("/upload", response_model=Project, status_code=status.HTTP_201_CREATED)
async def upload_project(
    file: UploadFile = File(..., description="A .zip archive of the project"),
    name: str | None = Form(default=None),
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
    settings: Settings = Depends(settings_dep),
):
    filename = file.filename or "project.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="only .zip archives are supported",
        )

    try:
        await projects.assert_quota_async(principal.tenant)
    except ProjectQuotaError as exc:
        raise quota_error(exc) from exc

    # Stream the body straight to disk in fixed-size chunks.
    #
    # The previous version accumulated the whole archive in a list and joined
    # it, so peak memory was twice the upload. That was survivable only because
    # a 50 MB ceiling capped it; with size limits removed (MAX_PROJECT_SIZE_MB=0
    # means unlimited) it would let a single large upload exhaust the worker and
    # take down every other request with it. Streaming keeps peak memory at one
    # chunk regardless of how large the project is.
    project = projects.reserve_upload(name or "", filename, principal.tenant)
    staging = projects.staging_path(project.id)
    limit = settings.max_project_size_mb * 1024 * 1024   # <= 0 means unlimited
    total = 0

    try:
        with staging.open("wb") as sink:
            while chunk := await file.read(UPLOAD_CHUNK):
                total += len(chunk)
                if 0 < limit < total:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"upload exceeds the {settings.max_project_size_mb} MB limit",
                    )
                # Written off the event loop: at gigabyte scale the accumulated
                # blocking write time is not negligible.
                await io_bound(sink.write, chunk)
        if total == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="the upload is empty"
            )
    except BaseException:
        # Includes client disconnect mid-upload. Never leave a partial archive
        # or an empty project behind.
        staging.unlink(missing_ok=True)
        await io_bound(projects.discard, project.id)
        raise

    try:
        project = await projects.create_from_archive_async(project, staging, filename)
        project = await projects.analyze_async(project.id, principal.tenant)
    except ProjectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await emit_simple(
        EventType.PROJECT_CREATED,
        f"Uploaded project '{project.name}'",
        project_id=project.id,
        source="upload",
    )
    return project


@router.get("/{project_id}", response_model=Project)
async def get_project(
    project_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
):
    return await owned_project(project_id, projects, principal.tenant)


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
):
    project = await owned_project(project_id, projects, principal.tenant)
    deleted = await projects.delete_async(project_id, principal.tenant)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
    await emit_simple(
        EventType.PROJECT_DELETED, f"Deleted project '{project.name}'", project_id=project_id
    )
    return {"deleted": True, "project_id": project_id}


@router.post("/{project_id}/analyze", response_model=Project)
async def analyze_project(
    project_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
):
    await owned_project(project_id, projects, principal.tenant)
    try:
        project = await projects.analyze_async(project_id, principal.tenant)
    except ProjectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    metadata = project.metadata
    await emit_simple(
        EventType.PROJECT_ANALYZED,
        (
            f"Analyzed '{project.name}': {metadata.framework} / {metadata.language}, "
            f"{len(metadata.routes)} route(s), {len(metadata.test_files)} test file(s)"
            if metadata else f"Analyzed '{project.name}'"
        ),
        project_id=project_id,
        routes=len(metadata.routes) if metadata else 0,
        tests=len(metadata.test_files) if metadata else 0,
    )
    return project


@router.get("/{project_id}/files")
async def project_files(
    project_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
):
    await owned_project(project_id, projects, principal.tenant)
    tree = await projects.file_tree_async(project_id, principal.tenant)
    return {"project_id": project_id, "tree": tree}


@router.get("/{project_id}/file", response_model=FileContent)
async def project_file(
    project_id: str,
    path: str = Query(..., description="Project-relative file path", max_length=1024),
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
):
    await owned_project(project_id, projects, principal.tenant)
    try:
        return await projects.read_file_async(project_id, path, principal.tenant)
    except ProjectError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{project_id}/routes")
async def project_routes(
    project_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
):
    await owned_project(project_id, projects, principal.tenant)
    project = await projects.ensure_analyzed_async(project_id, principal.tenant)
    metadata = project.metadata
    return {
        "project_id": project_id,
        "framework": metadata.framework if metadata else "unknown",
        "entry_point": metadata.entry_point if metadata else None,
        "routes": [route.model_dump(mode="json") for route in (metadata.routes if metadata else [])],
    }


@router.get("/{project_id}/export")
async def export_project(
    project_id: str,
    principal: Principal = Depends(current_principal),
    projects: ProjectService = Depends(project_service),
):
    """Export the project workspace (including any applied repairs/fixes) as a zip archive."""
    import tempfile
    import zipfile
    from pathlib import Path
    from fastapi.responses import FileResponse

    project = await owned_project(project_id, projects, principal.tenant)
    workspace = projects.workspace(project_id)
    if not workspace.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace directory not found"
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = Path(tmp.name)
    tmp.close()

    try:
        def archive_workspace():
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file_path in workspace.rglob("*"):
                    if file_path.is_file():
                        rel_parts = file_path.relative_to(workspace).parts
                        # Skip caches, pycache, git metadata
                        if any(part in ("__pycache__", ".pytest_cache", ".git", ".venv", "node_modules") for part in rel_parts):
                            continue
                        arcname = file_path.relative_to(workspace)
                        zipf.write(file_path, arcname)

        await io_bound(archive_workspace)

        safe_name = "".join(c for c in project.name if c.isalnum() or c in ("-", "_")).strip() or "project"
        filename = f"{safe_name}_fixed.zip"

        return FileResponse(
            path=tmp_path,
            media_type="application/zip",
            filename=filename,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not create export archive: {exc}",
        ) from exc

