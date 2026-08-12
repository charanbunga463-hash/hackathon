"""Apply a validated patch atomically.

Apply is all-or-nothing: a snapshot is taken first, then every file is written,
and if any write fails the snapshot is restored immediately. A patch is
re-validated at apply time even if it was validated when it was proposed —
the workspace may have changed between approval and application.
"""

from __future__ import annotations

from pathlib import Path

from ..config.settings import Settings
from ..models.patch import AppliedPatch, PatchProposal, PatchStatus, PatchValidation
from ..security.path_security import assert_editable
from ..utils.filesystem import write_text_atomic
from ..utils.logging import get_logger
from ..utils.timestamps import utcnow_iso
from .patch_validator import build_diff, validate_patch
from .snapshot_manager import SnapshotManager

logger = get_logger(__name__)


class PatchApplyError(RuntimeError):
    def __init__(self, message: str, validation: PatchValidation | None = None) -> None:
        super().__init__(message)
        self.validation = validation


def apply_patch(
    workspace: Path,
    patch: PatchProposal,
    snapshots: SnapshotManager,
    settings: Settings,
) -> tuple[AppliedPatch, PatchValidation]:
    """Validate → snapshot → write → verify-on-disk. Rolls back on any failure."""
    validation = validate_patch(workspace, patch, settings)
    if not validation.valid:
        messages = "; ".join(issue.message for issue in validation.errors)
        raise PatchApplyError(f"refusing to apply an invalid patch: {messages}", validation)

    diff, pending = build_diff(workspace, patch)
    changed_paths = [path for path in pending if _will_change(workspace, path, pending[path])]
    if not changed_paths:
        raise PatchApplyError("the patch would not change any file", validation)

    snapshot = snapshots.create(changed_paths, patch_id=patch.id, label=patch.title or "pre-patch")

    written: list[str] = []
    try:
        for relative in changed_paths:
            target = assert_editable(workspace, relative) if (workspace / relative).exists() else _prepare_new(workspace, relative)
            write_text_atomic(target, pending[relative])
            written.append(relative)
    except Exception as exc:  # noqa: BLE001 - any failure must roll back
        logger.error("patch %s failed mid-apply (%s); rolling back", patch.id, exc)
        snapshots.restore(snapshot.id)
        raise PatchApplyError(
            f"apply failed after writing {len(written)} file(s); the workspace was rolled back: {exc}",
            validation,
        ) from exc

    patch.status = PatchStatus.APPLIED
    patch.diff = diff
    applied = AppliedPatch(
        patch_id=patch.id,
        snapshot_id=snapshot.id,
        applied_at=utcnow_iso(),
        files_changed=written,
        diff=diff,
    )
    snapshots.prune(settings.keep_snapshots)
    logger.info("patch %s applied to %s", patch.id, ", ".join(written))
    return applied, validation


def _prepare_new(workspace: Path, relative: str) -> Path:
    """Path resolution for a file that does not exist yet."""
    from ..security.path_security import safe_join

    target = safe_join(workspace, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _will_change(workspace: Path, relative: str, new_content: str) -> bool:
    from ..utils.filesystem import read_text

    target = workspace / relative
    before = read_text(target) if target.exists() and target.is_file() else ""
    return before != new_content
