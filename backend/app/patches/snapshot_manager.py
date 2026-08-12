"""File snapshots taken immediately before a patch is applied.

A snapshot stores the exact bytes of every file the patch will touch, plus a
sha256 so a rollback can prove it restored the original content. Snapshots live
outside the workspace so project code cannot tamper with them.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from ..models.patch import FileSnapshot, Snapshot
from ..security.path_security import safe_join
from ..utils.filesystem import ensure_dir, read_json, rmtree, write_json_atomic
from ..utils.logging import get_logger

logger = get_logger(__name__)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SnapshotManager:
    def __init__(self, workspace: Path, snapshots_root: Path, project_id: str) -> None:
        self.workspace = workspace
        self.root = ensure_dir(snapshots_root)
        self.project_id = project_id

    def _dir(self, snapshot_id: str) -> Path:
        return self.root / snapshot_id

    def create(self, paths: list[str], *, patch_id: str | None = None, label: str = "") -> Snapshot:
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        directory = ensure_dir(self._dir(snapshot_id))
        files: list[FileSnapshot] = []

        for relative in dict.fromkeys(p.replace("\\", "/") for p in paths):
            target = safe_join(self.workspace, relative)
            if target.exists() and target.is_file():
                stored_name = relative.replace("/", "__")
                stored_path = directory / stored_name
                stored_path.write_bytes(target.read_bytes())
                files.append(
                    FileSnapshot(
                        path=relative,
                        existed=True,
                        sha256=sha256_file(target),
                        stored_as=stored_name,
                    )
                )
            else:
                # Record absence explicitly: rollback must delete a created file.
                files.append(FileSnapshot(path=relative, existed=False, sha256=None, stored_as=None))

        snapshot = Snapshot(
            id=snapshot_id,
            project_id=self.project_id,
            patch_id=patch_id,
            files=files,
            label=label,
        )
        write_json_atomic(directory / "snapshot.json", snapshot.model_dump(mode="json"))
        logger.info("snapshot %s captured %d files", snapshot_id, len(files))
        return snapshot

    def load(self, snapshot_id: str) -> Snapshot | None:
        payload = read_json(self._dir(snapshot_id) / "snapshot.json")
        if payload is None:
            return None
        return Snapshot.model_validate(payload)

    def restore(self, snapshot_id: str) -> tuple[bool, list[str], list[str]]:
        """Restore every file. Returns (ok, restored_paths, errors)."""
        snapshot = self.load(snapshot_id)
        if snapshot is None:
            return False, [], [f"snapshot {snapshot_id} not found"]

        directory = self._dir(snapshot_id)
        restored: list[str] = []
        errors: list[str] = []

        for entry in snapshot.files:
            try:
                target = safe_join(self.workspace, entry.path)
            except ValueError as exc:
                errors.append(f"{entry.path}: {exc}")
                continue
            if entry.existed and entry.stored_as:
                stored = directory / entry.stored_as
                if not stored.exists():
                    errors.append(f"{entry.path}: stored copy is missing from the snapshot")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(stored.read_bytes())
                if entry.sha256 and sha256_file(target) != entry.sha256:
                    errors.append(f"{entry.path}: checksum mismatch after restore")
                    continue
                restored.append(entry.path)
            else:
                # The file did not exist before the patch: remove what was created.
                if target.exists() and target.is_file():
                    target.unlink()
                restored.append(entry.path)

        if not errors:
            snapshot.restored = True
            write_json_atomic(directory / "snapshot.json", snapshot.model_dump(mode="json"))
        return not errors, restored, errors

    def list_snapshots(self) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        if not self.root.exists():
            return snapshots
        for directory in sorted(self.root.iterdir(), reverse=True):
            if not directory.is_dir():
                continue
            payload = read_json(directory / "snapshot.json")
            if payload:
                snapshots.append(Snapshot.model_validate(payload))
        return snapshots

    def prune(self, keep: int) -> int:
        """Drop the oldest snapshots beyond `keep`. Returns how many were removed."""
        snapshots = sorted(self.list_snapshots(), key=lambda s: s.created_at, reverse=True)
        removed = 0
        for snapshot in snapshots[keep:]:
            rmtree(self._dir(snapshot.id))
            removed += 1
        return removed
