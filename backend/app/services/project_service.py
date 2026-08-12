"""Project lifecycle: create, analyse, browse, delete.

Persistence sits behind the `ProjectStore` protocol. The shipped implementation
is filesystem + JSON; swapping in PostgreSQL means writing one more class, not
touching the routes or the agent.

On-disk layout:

    data/projects/<project_id>/
        project.json        metadata record
        workspace/          the project's actual source (the only thing executed)
        snapshots/          pre-patch file snapshots
        sessions/           repair session records
"""

from __future__ import annotations

import contextlib
import re
import shutil
import uuid
from pathlib import Path
from typing import Callable, Protocol

from ..analysis.project_analyzer import analyze_project, build_file_tree, language_for
from ..config.settings import Settings
from ..models.project import (
    FileContent,
    Project,
    ProjectMetadata,
    ProjectSource,
    ProjectStatus,
    ProjectSummary,
)
from ..runtime.concurrency import cpu_bound, io_bound
from ..security.archive_security import (
    ArchiveSecurityError,
    ExtractionLimits,
    safe_extract_zip,
)
from ..security.path_security import PathSecurityError, safe_join
from ..utils.filesystem import (
    collapse_single_root,
    ensure_dir,
    read_json,
    read_text,
    rmtree,
    write_json_atomic,
)
from ..utils.logging import get_logger
from ..utils.timestamps import utcnow_iso

logger = get_logger(__name__)

SAFE_NAME = re.compile(r"[^A-Za-z0-9._\- ]+")


class ProjectError(RuntimeError):
    pass


class ProjectQuotaError(ProjectError):
    """Raised when a tenant is at its project or storage quota."""


class ProjectAccessError(ProjectError):
    """Raised when a tenant asks for a project it does not own."""


class ProjectStore(Protocol):
    """Persistence boundary. Implement this to move to a database."""

    def save(self, project: Project) -> None: ...
    def load(self, project_id: str) -> Project | None: ...
    def list(self, owner: str | None = None) -> list[Project]: ...
    def delete(self, project_id: str) -> bool: ...


class JsonProjectStore:
    """Filesystem store with an in-process read cache.

    Listing used to open and parse every `project.json` on every request, which
    is O(projects) disk reads per page load — fine at 5 projects, ruinous at 500
    under concurrent users. Records are cached by mtime, so a warm list costs a
    `stat` per project instead of a read + parse.
    """

    def __init__(self, root: Path) -> None:
        self.root = ensure_dir(root)
        self._cache: dict[str, tuple[float, Project]] = {}

    def _dir(self, project_id: str) -> Path:
        return self.root / project_id

    def _record_path(self, project_id: str) -> Path:
        return self._dir(project_id) / "project.json"

    def save(self, project: Project) -> None:
        project.touch()
        directory = ensure_dir(self._dir(project.id))
        path = directory / "project.json"
        write_json_atomic(path, project.model_dump(mode="json"))
        try:
            self._cache[project.id] = (path.stat().st_mtime, project.model_copy(deep=True))
        except OSError:
            self._cache.pop(project.id, None)

    def load(self, project_id: str) -> Project | None:
        path = self._record_path(project_id)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            self._cache.pop(project_id, None)
            return None

        cached = self._cache.get(project_id)
        if cached is not None and cached[0] == mtime:
            return cached[1].model_copy(deep=True)

        payload = read_json(path)
        if payload is None:
            return None
        try:
            project = Project.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - a corrupt record must not 500 the list
            logger.warning("skipping unreadable project record %s: %s", project_id, exc)
            return None
        self._cache[project_id] = (mtime, project.model_copy(deep=True))
        return project

    def list(self, owner: str | None = None) -> list[Project]:
        projects: list[Project] = []
        if not self.root.exists():
            return projects
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            project = self.load(directory.name)
            if project is None:
                continue
            if owner is not None and project.owner != owner:
                continue
            projects.append(project)
        return sorted(projects, key=lambda p: p.updated_at, reverse=True)

    def delete(self, project_id: str) -> bool:
        directory = self._dir(project_id)
        self._cache.pop(project_id, None)
        if not directory.exists():
            return False
        rmtree(directory)
        return True


def sanitize_name(raw: str, fallback: str = "project") -> str:
    cleaned = SAFE_NAME.sub("", (raw or "").strip())[:80].strip()
    return cleaned or fallback


def build_project_store(settings: Settings) -> ProjectStore:
    """Postgres when a database is configured, JSON files otherwise.

    Either way the project's *workspace* stays on disk — it is a source tree
    that pytest and Docker execute against, not data.
    """
    from ..db import database_enabled

    if database_enabled():
        from ..db.stores import PostgresProjectStore

        return PostgresProjectStore()
    return JsonProjectStore(settings.projects_dir)


class ProjectService:
    def __init__(self, settings: Settings, store: ProjectStore | None = None) -> None:
        self.settings = settings
        self.store = store or build_project_store(settings)

    # ------------------------------------------------------------ tenancy --
    def owned(self, project_id: str, tenant: str | None) -> Project:
        """Load a project, enforcing ownership.

        A missing project and someone else's project both raise the same
        not-found error on purpose: distinguishing them would let a caller probe
        which project ids exist.
        """
        project = self.store.load(project_id)
        if project is None or (tenant is not None and project.owner != tenant):
            raise ProjectError(f"project {project_id} not found")
        return project

    def assert_quota(self, tenant: str) -> None:
        """Refuse an upload that would exceed this tenant's quota.

        MAX_STORAGE_PER_TENANT_MB of 0 means unlimited. The guard matters: a
        naive `used >= 0` comparison is true for a brand-new account with no
        storage at all, so without it a limit of 0 would reject *every* upload
        rather than allowing all of them.
        """
        storage_budget = self.settings.max_storage_per_tenant_mb * 1024 * 1024
        project_budget = self.settings.max_projects_per_tenant

        def check(used_count: int, used_bytes: int) -> None:
            if project_budget > 0 and used_count >= project_budget:
                raise ProjectQuotaError(
                    f"project limit reached ({project_budget}). "
                    "Delete an existing project before adding another."
                )
            if storage_budget > 0 and used_bytes >= storage_budget:
                raise ProjectQuotaError(
                    f"storage limit reached ({self.settings.max_storage_per_tenant_mb} MB used). "
                    "Delete a project to free space."
                )

        # Postgres answers both questions with a COUNT and a SUM; the JSON store
        # has to load every record, which is why it only does so when asked.
        counter = getattr(self.store, "count_for", None)
        sizer = getattr(self.store, "storage_used", None)
        if counter is not None and sizer is not None:
            check(counter(tenant), sizer(tenant))
            return

        # Skip the listing entirely when neither budget is enforced.
        if project_budget <= 0 and storage_budget <= 0:
            return

        projects = self.store.list(owner=tenant)
        check(
            len(projects),
            sum(
                (project.metadata.total_size_bytes if project.metadata else 0)
                for project in projects
            ),
        )

    def storage_used_bytes(self, tenant: str) -> int:
        sizer = getattr(self.store, "storage_used", None)
        if sizer is not None:
            return sizer(tenant)
        return sum(
            (project.metadata.total_size_bytes if project.metadata else 0)
            for project in self.store.list(owner=tenant)
        )

    def usage(self, tenant: str) -> dict:
        counter = getattr(self.store, "count_for", None)
        sizer = getattr(self.store, "storage_used", None)
        if counter is not None and sizer is not None:
            count, used = counter(tenant), sizer(tenant)
        else:
            projects = self.store.list(owner=tenant)
            count = len(projects)
            used = sum((p.metadata.total_size_bytes if p.metadata else 0) for p in projects)
        return {
            "tenant": tenant,
            "projects": count,
            "max_projects": self.settings.max_projects_per_tenant,
            "storage_bytes": used,
            "max_storage_bytes": self.settings.max_storage_per_tenant_mb * 1024 * 1024,
        }

    # ----------------------------------------------------------- layout ---
    def project_dir(self, project_id: str) -> Path:
        return self.settings.projects_dir / project_id

    def workspace(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "workspace"

    def snapshots_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "snapshots"

    def sessions_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "sessions"

    # ------------------------------------------------------------ CRUD ----
    def list_projects(self, tenant: str | None = None) -> list[ProjectSummary]:
        """Summaries for one tenant, scoped at the store rather than in Python.

        A store that can build summaries without materialising every full
        project record does so — see `PostgresProjectStore.list_summaries`. The
        JSON store has to read the files either way, so it falls back to
        projecting in memory.
        """
        summarise = getattr(self.store, "list_summaries", None)
        if summarise is not None:
            return summarise(owner=tenant)
        return [
            ProjectSummary.from_project(project) for project in self.store.list(owner=tenant)
        ]

    def get(self, project_id: str, tenant: str | None = None) -> Project:
        return self.owned(project_id, tenant)

    def delete(self, project_id: str, tenant: str | None = None) -> bool:
        """Remove the record AND the workspace.

        Both halves are required, and which one the store handles depends on the
        store: `JsonProjectStore` keeps the record inside the project directory
        so deleting it takes the workspace with it, while `PostgresProjectStore`
        deletes a row and leaves the filesystem entirely alone. Relying on the
        store alone therefore leaked the whole workspace on every delete under
        Postgres — invisible while uploads were capped at 50 MB, unbounded once
        they were not.

        The record goes first: if the directory removal fails (a file locked by
        a still-draining test run, say) the project is already gone from every
        listing, and what is left is recoverable disk rather than a ghost
        project the user cannot get rid of.
        """
        self.owned(project_id, tenant)
        deleted = self.store.delete(project_id)
        directory = self.project_dir(project_id)
        if directory.exists():
            try:
                rmtree(directory)
            except Exception as exc:  # noqa: BLE001 - the record is already gone
                logger.error(
                    "project %s was deleted but its workspace could not be "
                    "removed from %s: %s", project_id, directory, exc,
                )
        return deleted

    def _new_project(
        self,
        name: str,
        source: ProjectSource,
        origin: str | None,
        description: str | None = None,
        owner: str = "public",
    ) -> Project:
        project = Project(
            id=f"prj_{uuid.uuid4().hex[:12]}",
            name=sanitize_name(name),
            source=source,
            owner=owner,
            origin=origin,
            description=description,
        )
        ensure_dir(self.workspace(project.id))
        ensure_dir(self.snapshots_dir(project.id))
        ensure_dir(self.sessions_dir(project.id))
        return project

    # ----------------------------------------------------- zip ingestion ---
    def extraction_limits(self) -> ExtractionLimits:
        """The configured policy. A setting of 0 means unlimited (see Settings)."""
        return ExtractionLimits(
            max_archive_bytes=self.settings.max_project_size_mb * 1024 * 1024,
            max_total_uncompressed_bytes=self.settings.max_extracted_size_mb * 1024 * 1024,
            max_file_bytes=self.settings.max_file_size_mb * 1024 * 1024,
            max_file_count=self.settings.max_file_count,
            max_compression_ratio=self.settings.max_compression_ratio,
        )

    def staging_path(self, project_id: str) -> Path:
        return ensure_dir(self.settings.uploads_dir) / f"{project_id}.zip"

    def discard(self, project_id: str) -> None:
        """Undo a `reserve_upload` whose upload never completed.

        `_new_project` creates the workspace directories but writes no record,
        so an abandoned upload leaves empty directories rather than a visible
        project. This removes them; the store delete is defensive, for the case
        where a record did get written before the failure.
        """
        with contextlib.suppress(Exception):
            rmtree(self.project_dir(project_id))
        with contextlib.suppress(Exception):
            self.store.delete(project_id)

    def reserve_upload(self, name: str, filename: str, owner: str) -> Project:
        """Allocate the project id (and therefore its staging path) up front.

        The route needs somewhere to stream the request body *before* it knows
        whether the archive is valid, and the staging file has to be namespaced
        per project so two concurrent uploads cannot overwrite each other.
        """
        display_name = name or Path(filename).stem or "uploaded-project"
        return self._new_project(display_name, ProjectSource.UPLOAD, filename, owner=owner)

    def create_from_zip(
        self, filename: str, data: bytes, name: str | None = None, owner: str = "public"
    ) -> Project:
        """Import an archive already held in memory.

        Retained for callers that genuinely have the bytes (tests, the migration
        script). The HTTP upload path does NOT use this — it streams to disk and
        calls `create_from_archive`, so request size never becomes memory use.
        """
        project = self.reserve_upload(name or "", filename, owner)
        staging = self.staging_path(project.id)
        staging.write_bytes(data)
        return self.create_from_archive(project, staging, filename)

    def create_from_archive(
        self, project: Project, archive_path: Path, filename: str
    ) -> Project:
        """Extract a staged archive into the project's workspace.

        `archive_path` is consumed: it is removed whether extraction succeeds or
        fails, so a rejected upload leaves nothing behind on disk.
        """
        try:
            report = safe_extract_zip(
                archive_path, self.workspace(project.id), self.extraction_limits()
            )
        except ArchiveSecurityError as exc:
            rmtree(self.project_dir(project.id))
            raise ProjectError(str(exc)) from exc
        finally:
            archive_path.unlink(missing_ok=True)

        collapse_single_root(self.workspace(project.id))
        report.root_collapsed = True
        project.upload_report = report.as_dict()
        project.status = ProjectStatus.READY
        self.store.save(project)
        logger.info(
            "created project %s from upload %s (%d files, %.1f MB)",
            project.id, filename, report.files_written, report.bytes_written / 1e6,
        )
        return project

    # --------------------------------------------------------- analysis ---
    def analyze(self, project_id: str) -> Project:
        project = self.get(project_id)
        project.status = ProjectStatus.ANALYZING
        self.store.save(project)
        try:
            metadata: ProjectMetadata = analyze_project(self.workspace(project_id))
        except Exception as exc:  # noqa: BLE001
            project.status = ProjectStatus.ERROR
            project.error = f"analysis failed: {exc}"
            self.store.save(project)
            raise ProjectError(project.error) from exc
        project.metadata = metadata
        project.status = ProjectStatus.READY
        project.error = None
        self.store.save(project)
        return project

    def ensure_analyzed(self, project_id: str) -> Project:
        project = self.get(project_id)
        if project.metadata is None:
            return self.analyze(project_id)
        return project

    # ---------------------------------------------------------- browsing --
    def file_tree(self, project_id: str) -> list[dict]:
        return build_file_tree(self.workspace(project_id))

    def read_file(self, project_id: str, relative: str, max_bytes: int = 400_000) -> FileContent:
        workspace = self.workspace(project_id)
        try:
            target = safe_join(workspace, relative)
        except PathSecurityError as exc:
            raise ProjectError(str(exc)) from exc
        if not target.exists() or not target.is_file():
            raise ProjectError(f"file not found: {relative}")
        size = target.stat().st_size
        content = read_text(target, max_bytes=max_bytes)
        return FileContent(
            path=relative.replace("\\", "/"),
            content=content,
            lines=len(content.splitlines()),
            size=size,
            truncated=size > max_bytes,
            language=language_for(relative),
        )

    # ------------------------------------------------------------ status --
    async def mutate(self, project_id: str, apply: Callable[[Project], None]) -> Project:
        """Read-modify-write a project record under a distributed lock.

        Without the lock this is a textbook lost update: two concurrent runs
        both read `failures_detected == 3`, both write `4`, and one run's count
        vanishes. With multiple workers the window is milliseconds wide and hit
        constantly, so the lock is held across the whole read-modify-write
        rather than around the write alone.
        """
        from ..runtime.concurrency import io_bound
        from ..runtime.state import get_state_backend

        async with get_state_backend().lock(f"project:{project_id}", ttl=15.0, timeout=15.0):
            project = await io_bound(self.store.load, project_id)
            if project is None:
                raise ProjectError(f"project {project_id} not found")
            apply(project)
            await io_bound(self.store.save, project)
            return project

    async def set_status(
        self, project_id: str, status: ProjectStatus, error: str | None = None
    ) -> Project:
        def apply(project: Project) -> None:
            project.status = status
            project.error = error

        return await self.mutate(project_id, apply)

    async def record_run(
        self,
        project_id: str,
        *,
        failures: int,
        verdict: str | None = None,
        attempted: bool = False,
        verified: bool = False,
    ) -> Project | None:
        """Update a project's rollup counters. Best-effort by design.

        These are derived counters; the execution record on disk is the source
        of truth. Under heavy contention on one project the lock can time out,
        and failing the whole run because a *statistic* could not be written
        would turn a successful repair into a 500. Log it and move on.
        """

        def apply(project: Project) -> None:
            project.stats.failures_detected += failures
            if attempted:
                project.stats.repairs_attempted += 1
            if verified:
                project.stats.repairs_verified += 1
            project.stats.last_run_at = utcnow_iso()
            project.stats.last_verdict = verdict
            if verified:
                project.status = ProjectStatus.REPAIRED
            elif failures:
                project.status = ProjectStatus.FAILING
            else:
                project.status = ProjectStatus.HEALTHY

        from ..runtime.state import LockTimeout

        try:
            project = await self.mutate(project_id, apply)
        except LockTimeout:
            logger.warning(
                "could not update rollup stats for %s: the project lock was contended. "
                "The execution record itself was persisted.",
                project_id,
            )
            return None
        await self.invalidate_caches(project.owner)
        return project

    def save(self, project: Project) -> None:
        self.store.save(project)

    # -----------------------------------------------------------------------
    # Async surface
    #
    # Everything below runs the blocking body in a worker thread. These are what
    # the routes call; the sync methods remain for tests and background workers
    # that are already off the loop.
    # -----------------------------------------------------------------------
    async def list_projects_async(self, tenant: str | None = None) -> list[ProjectSummary]:
        from ..runtime.cache import get_cache

        return await get_cache().get_or_compute(
            ("projects", tenant),
            lambda: io_bound(self.list_projects, tenant),
            ttl=self.settings.aggregate_cache_seconds,
        )

    async def get_async(self, project_id: str, tenant: str | None = None) -> Project:
        return await io_bound(self.get, project_id, tenant)

    async def delete_async(self, project_id: str, tenant: str | None = None) -> bool:
        result = await io_bound(self.delete, project_id, tenant)
        await self.invalidate_caches(tenant)
        return result

    async def invalidate_caches(self, tenant: str | None) -> None:
        """Drop cached aggregates after a write, on every worker.

        Local-only invalidation was correct when each worker had its own
        filesystem. Against one shared database it is not: the worker that
        handled the write clears its cache while every other worker keeps
        serving its own stale copy until the TTL lapses.
        """
        from ..runtime.cache import get_cache
        from ..runtime.shared_cache import invalidate

        cache = get_cache()
        await cache.invalidate(
            ("projects", tenant), ("dashboard", tenant), ("files", tenant)
        )
        await cache.invalidate_prefix("history")
        await invalidate(f"dashboard:{tenant}", prefixes=("shared",))

    async def usage_async(self, tenant: str) -> dict:
        return await io_bound(self.usage, tenant)

    async def assert_quota_async(self, tenant: str) -> None:
        await io_bound(self.assert_quota, tenant)

    async def create_from_zip_async(
        self, filename: str, data: bytes, name: str | None = None, owner: str = "public"
    ) -> Project:
        # Extraction is disk-bound and can take seconds on a large archive.
        project = await io_bound(self.create_from_zip, filename, data, name, owner)
        await self.invalidate_caches(owner)
        return project

    async def create_from_archive_async(
        self, project: Project, archive_path: Path, filename: str
    ) -> Project:
        """Extract a staged archive off the event loop.

        Unbounded archives make this genuinely long-running, so it must never
        run inline — a multi-minute extraction on the loop would stall every
        other request on the worker.
        """
        created = await io_bound(self.create_from_archive, project, archive_path, filename)
        await self.invalidate_caches(project.owner)
        return created

    async def analyze_async(self, project_id: str, tenant: str | None = None) -> Project:
        self.owned(project_id, tenant)
        # AST parsing across a whole repository is the single most expensive
        # synchronous call in the app; it must never run on the event loop.
        project = await cpu_bound(self.analyze, project_id)
        await self.invalidate_caches(tenant)
        return project

    async def ensure_analyzed_async(self, project_id: str, tenant: str | None = None) -> Project:
        project = await self.get_async(project_id, tenant)
        if project.metadata is None:
            return await self.analyze_async(project_id, tenant)
        return project

    async def file_tree_async(self, project_id: str, tenant: str | None = None) -> list[dict]:
        from ..runtime.cache import get_cache

        self.owned(project_id, tenant)
        # Walking a repository tree is many stat() calls; the tree only changes
        # when a patch is applied, so a short TTL is safe and very effective.
        return await get_cache().get_or_compute(
            ("filetree", project_id),
            lambda: io_bound(self.file_tree, project_id),
            ttl=self.settings.aggregate_cache_seconds,
        )

    async def read_file_async(
        self, project_id: str, relative: str, tenant: str | None = None
    ) -> FileContent:
        self.owned(project_id, tenant)
        return await io_bound(self.read_file, project_id, relative)
