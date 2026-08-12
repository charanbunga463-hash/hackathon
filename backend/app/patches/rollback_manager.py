"""Rollback of an applied patch.

Called automatically when verification fails and a retry needs a clean tree, and
manually from the UI. Rollback is verified: every restored file's sha256 must
match what the snapshot recorded, otherwise the rollback reports failure rather
than silently leaving a half-reverted workspace.
"""

from __future__ import annotations

from pathlib import Path

from ..models.patch import AppliedPatch, PatchProposal, PatchStatus
from ..utils.logging import get_logger
from ..utils.timestamps import utcnow_iso
from .snapshot_manager import SnapshotManager

logger = get_logger(__name__)


class RollbackError(RuntimeError):
    pass


def rollback_patch(
    workspace: Path,
    applied: AppliedPatch,
    snapshots: SnapshotManager,
    *,
    reason: str = "",
    patch: PatchProposal | None = None,
) -> AppliedPatch:
    if applied.rolled_back:
        return applied

    ok, restored, errors = snapshots.restore(applied.snapshot_id)
    if not ok:
        raise RollbackError(
            f"rollback of patch {applied.patch_id} failed: {'; '.join(errors)}"
        )

    applied.rolled_back = True
    applied.rolled_back_at = utcnow_iso()
    applied.rollback_reason = reason or "rolled back"
    if patch is not None:
        patch.status = PatchStatus.ROLLED_BACK
    logger.info(
        "patch %s rolled back (%d files restored): %s",
        applied.patch_id, len(restored), reason or "no reason given",
    )
    return applied


def rollback_to_snapshot(
    snapshots: SnapshotManager, snapshot_id: str
) -> tuple[bool, list[str], list[str]]:
    return snapshots.restore(snapshot_id)
