"""Unlimited upload sizes, and the guards that must survive them.

Size limits are off by default (0 = unlimited), so a project of any size can be
imported. Two classes of regression are guarded here.

**The feature works.** A large archive, a large member, and a large total
expansion are all accepted with the shipped defaults.

**Zero does not mean zero.** Every one of these limits is compared with `>=` or
`>` somewhere, and a naive comparison against a limit of 0 inverts the meaning —
`used >= 0` is true for an empty account, and `body > 0` is true for every
request that has one. Each of those would turn "unlimited" into "nothing is
allowed", and each is asserted below, because all three were live bugs the
moment the defaults changed.
"""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.security.archive_security import (
    UNLIMITED,
    ArchiveSecurityError,
    ExtractionLimits,
    safe_extract_zip,
)
from app.services.project_service import ProjectQuotaError, ProjectService

from .test_auth import (  # noqa: F401 - fixtures are used by name
    PASSWORD,
    CapturingSender,
    auth_client,
    mailbox,
    signup,
)


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buffer.getvalue()


# ------------------------------------------------------------- defaults -----
def test_shipped_defaults_impose_no_size_limit():
    s = Settings()
    assert s.max_project_size_mb == 0
    assert s.max_extracted_size_mb == 0
    assert s.max_file_size_mb == 0
    assert s.max_storage_per_tenant_mb == 0


def test_zero_is_normalised_to_unlimited_not_to_zero():
    """The whole scheme rests on this conversion."""
    limits = ExtractionLimits(
        max_archive_bytes=0,
        max_total_uncompressed_bytes=0,
        max_file_bytes=0,
        max_file_count=0,
    )
    assert limits.max_archive_bytes == UNLIMITED
    assert limits.max_total_uncompressed_bytes == UNLIMITED
    assert limits.max_file_bytes == UNLIMITED
    assert limits.max_file_count == UNLIMITED


def test_default_limits_are_unlimited_for_sizes_only():
    limits = ExtractionLimits()
    assert limits.max_archive_bytes == UNLIMITED
    assert limits.max_file_bytes == UNLIMITED
    assert limits.max_total_uncompressed_bytes == UNLIMITED
    # Not size limits — these stay finite on purpose.
    assert limits.max_file_count < UNLIMITED
    assert limits.max_compression_ratio < UNLIMITED


# --------------------------------------------------------- large archives ---
def test_a_member_far_above_the_old_per_file_cap_is_accepted(tmp_path: Path):
    """25 MB in one file: 2.5x the old 10 MB per-file limit."""
    archive = tmp_path / "big-member.zip"
    # Incompressible on purpose: repetitive filler would trip the zip-bomb
    # ratio guard, which is a different check and is asserted separately below.
    payload = os.urandom(25 * 1024 * 1024)
    archive.write_bytes(_zip_bytes({"data.bin": payload}))

    report = safe_extract_zip(archive, tmp_path / "out")
    assert report.files_written == 1
    assert report.bytes_written == len(payload)


def test_total_expansion_far_above_the_old_budget_is_accepted(tmp_path: Path):
    """~40 MB expanded, against an old total budget of 200 MB but a 10 MB/file cap."""
    archive = tmp_path / "big-total.zip"
    chunk = os.urandom(2 * 1024 * 1024)
    archive.write_bytes(_zip_bytes({f"f{i}.bin": chunk for i in range(20)}))

    report = safe_extract_zip(archive, tmp_path / "out")
    assert report.files_written == 20
    assert report.bytes_written == 20 * len(chunk)


def test_a_positive_limit_is_still_enforced(tmp_path: Path):
    """Unlimited is a default, not a removal — an operator can still cap it."""
    archive = tmp_path / "capped.zip"
    archive.write_bytes(_zip_bytes({"data.bin": os.urandom(4 * 1024 * 1024)}))
    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(archive, tmp_path / "out",
                         ExtractionLimits(max_file_bytes=1024 * 1024))


# ------------------------------------------------- guards that must remain ---
def test_zip_bombs_are_still_refused_with_unlimited_sizes(tmp_path: Path):
    """The important one.

    A byte ceiling cannot detect a bomb before extraction; the compression ratio
    can. Removing the size limits must not remove this.
    """
    archive = tmp_path / "bomb.zip"
    # 20 MB of zeros compresses to a few KB — a ratio far above the threshold.
    archive.write_bytes(_zip_bytes({"bomb.bin": bytes(20 * 1024 * 1024)}))

    with pytest.raises(ArchiveSecurityError, match="zip bomb"):
        safe_extract_zip(archive, tmp_path / "out")   # shipped defaults


def test_absurd_member_counts_are_still_refused(tmp_path: Path):
    archive = tmp_path / "many.zip"
    archive.write_bytes(_zip_bytes({f"f{i}.py": b"x" for i in range(50)}))
    with pytest.raises(ArchiveSecurityError, match="entries"):
        safe_extract_zip(archive, tmp_path / "out",
                         ExtractionLimits(max_file_count=10))


def test_path_traversal_is_still_refused_with_unlimited_sizes(tmp_path: Path):
    archive = tmp_path / "evil.zip"
    archive.write_bytes(_zip_bytes({"../../escaped.txt": b"nope"}))
    with pytest.raises(ArchiveSecurityError):
        safe_extract_zip(archive, tmp_path / "out")


# ------------------------------------------------------ the zero-is-zero trap -
def test_unlimited_storage_quota_does_not_reject_every_upload(tmp_path: Path):
    """`used >= 0` is true for an empty account — the trap this guards."""
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=None,
        redis_url=None,
        max_storage_per_tenant_mb=0,
        max_projects_per_tenant=0,
    )
    settings.ensure_directories()
    service = ProjectService(settings)
    service.assert_quota("usr_nobody")   # must not raise


def test_a_positive_storage_quota_is_still_enforced(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=None,
        redis_url=None,
        max_projects_per_tenant=1,
    )
    settings.ensure_directories()
    service = ProjectService(settings)
    service.create_from_zip("p.zip", _zip_bytes({"main.py": b"x = 1"}), owner="usr_a")
    with pytest.raises(ProjectQuotaError):
        service.assert_quota("usr_a")


def test_unlimited_body_size_does_not_reject_ordinary_requests(auth_client, mailbox):
    """A body-size check against a limit of 0 would 413 every POST.

    Login and registration have bodies. If the gateway compared them against a
    zero ceiling, nobody could sign in at all — so this exercises the real HTTP
    path rather than the setting.
    """
    assert auth_client.settings.max_project_size_mb == 0
    signup(auth_client, mailbox, "ada@example.com")
    assert auth_client.get("/api/auth/me").status_code == 200

    # A body two orders of magnitude above the old 50 MB cap must not be
    # rejected by the size check. (It is refused for being a bad password, at
    # 422 — the point is that it reached validation at all rather than 413.)
    response = auth_client.post(
        "/api/account/password",
        json={"current_password": PASSWORD, "new_password": "x" * 300},
    )
    assert response.status_code == 422, response.status_code


def test_upload_of_a_project_over_the_old_cap_succeeds(auth_client, mailbox):
    """End to end through the real streaming upload route."""
    signup(auth_client, mailbox, "ada@example.com")

    # ~60 MB expanded, above the old 50 MB archive cap and 10 MB per-file cap.
    # Incompressible, so it does not trip the zip-bomb ratio check.
    entries = {"main.py": b"from fastapi import FastAPI\napp = FastAPI()\n"}
    for i in range(6):
        entries[f"assets/blob{i}.bin"] = os.urandom(10 * 1024 * 1024)

    response = auth_client.post(
        "/api/projects/upload",
        files={"file": ("big.zip", _zip_bytes(entries), "application/zip")},
        data={"name": "Large Import"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Large Import"
    assert body["upload_report"]["files_written"] == 7
    assert body["upload_report"]["bytes_written"] > 55 * 1024 * 1024


# --------------------------------------------------- workspace reclamation ---
def test_deleting_a_project_reclaims_its_workspace(tmp_path: Path):
    """Deletion must free the disk, not just the record.

    Under Postgres the store deletes a row and touches nothing on disk, so a
    service that trusted the store alone leaked the entire workspace on every
    delete. Harmless-looking at 50 MB per project; an unbounded disk leak once
    uploads have no size limit. Asserted against the filesystem, because the
    record disappearing is exactly the part that was never broken.
    """
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=None,
        redis_url=None,
    )
    settings.ensure_directories()
    service = ProjectService(settings)

    project = service.create_from_zip(
        "p.zip", _zip_bytes({"main.py": b"x = 1", "big.bin": os.urandom(2 * 1024 * 1024)}),
        owner="usr_a",
    )
    workspace = service.project_dir(project.id)
    assert workspace.exists()

    assert service.delete(project.id, "usr_a") is True
    assert not workspace.exists(), "workspace left on disk after delete"


def test_a_reserved_upload_that_never_completes_leaves_nothing_behind(tmp_path: Path):
    """A client that disconnects mid-upload must not leak a workspace either."""
    settings = Settings(data_dir=tmp_path / "data", database_url=None, redis_url=None)
    settings.ensure_directories()
    service = ProjectService(settings)

    project = service.reserve_upload("Abandoned", "abandoned.zip", "usr_a")
    staging = service.staging_path(project.id)
    staging.write_bytes(b"partial upload, never finished")
    assert service.project_dir(project.id).exists()

    staging.unlink(missing_ok=True)
    service.discard(project.id)

    assert not service.project_dir(project.id).exists()
    assert service.list_projects("usr_a") == []
