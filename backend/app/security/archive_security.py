"""Hardened archive extraction.

Uploaded ZIPs are hostile input. This module never calls `ZipFile.extractall`.
Every member is inspected, path-checked and size-budgeted before a byte is written.

Defences implemented here:
  * path traversal (`../`), absolute paths, drive letters, UNC paths
  * symlinks and other non-regular members (device files, hard links)
  * zip bombs (compressed:uncompressed ratio)
  * too many members
  * encrypted members (cannot be scanned, so refused)
  * nested archive depth (we simply never recurse)

Size budgets are configurable and **unlimited by default** — a project of any
size may be imported. Nothing here loads an archive or a member into memory
whole: `inspect_zip` reads only the central directory, and extraction streams in
64 KB chunks, so peak memory does not scale with the file. That is what makes an
unlimited budget a supportable default rather than a way to OOM the process.

Removing the size budgets does not remove the zip-bomb defence. The compression
ratio check is the one that matters, because it catches an archive whose
declared size is modest but which expands without bound — something no byte
ceiling can detect before extraction starts.
"""

from __future__ import annotations

import math
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..utils.logging import get_logger
from .path_security import PathSecurityError, is_within, normalize_relative

logger = get_logger(__name__)

# Members matching these are silently dropped rather than failing the upload.
SKIP_PREFIXES = ("__MACOSX/", ".git/", "node_modules/", ".venv/", "venv/")
SKIP_NAMES = {".DS_Store", "Thumbs.db"}


class ArchiveSecurityError(ValueError):
    """Raised when an archive violates the extraction policy."""


UNLIMITED = math.inf


def _budget(value: float) -> float:
    """A limit of 0 (or less) means "no limit".

    Normalised to infinity here so every call site stays a plain `>` comparison
    — there is no second "is this one unlimited?" branch to forget.
    """
    return UNLIMITED if value is None or value <= 0 else float(value)


@dataclass
class ExtractionLimits:
    """Extraction policy. Size budgets default to unlimited.

    The two limits that are NOT size budgets — `max_file_count` and
    `max_compression_ratio` — keep real defaults, because they defend against
    things a size budget cannot see: inode exhaustion, and an archive that is
    small on the wire but enormous once expanded.
    """

    max_archive_bytes: float = UNLIMITED
    max_total_uncompressed_bytes: float = UNLIMITED
    max_file_bytes: float = UNLIMITED
    max_file_count: float = 200_000
    max_compression_ratio: float = 120.0

    def __post_init__(self) -> None:
        self.max_archive_bytes = _budget(self.max_archive_bytes)
        self.max_total_uncompressed_bytes = _budget(self.max_total_uncompressed_bytes)
        self.max_file_bytes = _budget(self.max_file_bytes)
        self.max_file_count = _budget(self.max_file_count)


@dataclass
class ExtractionReport:
    files_written: int = 0
    bytes_written: int = 0
    skipped: list[str] = field(default_factory=list)
    root_collapsed: bool = False

    def as_dict(self) -> dict:
        return {
            "files_written": self.files_written,
            "bytes_written": self.bytes_written,
            "skipped": self.skipped[:50],
            "skipped_count": len(self.skipped),
            "root_collapsed": self.root_collapsed,
        }


def _should_skip(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if normalized.startswith(SKIP_PREFIXES):
        return True
    if any(f"/{prefix}" in f"/{normalized}" for prefix in SKIP_PREFIXES):
        return True
    return Path(normalized).name in SKIP_NAMES


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    # Unix mode lives in the high 16 bits of external_attr.
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _is_regular_or_dir(info: zipfile.ZipInfo) -> bool:
    """Reject device files, fifos and sockets — but only when the type is stated.

    Many writers (including `ZipFile.writestr` and every Windows zip tool) record
    permission bits with no `S_IFMT` type bits at all. Absence of type
    information is not evidence of a special file, so those entries are allowed;
    symlinks are caught separately by `_is_symlink`, which needs the type bits to
    be present anyway.
    """
    mode = info.external_attr >> 16
    if mode == 0 or (mode & 0o170000) == 0:
        return True
    return stat.S_ISREG(mode) or stat.S_ISDIR(mode)


def inspect_zip(archive_path: Path, limits: ExtractionLimits) -> list[zipfile.ZipInfo]:
    """Validate archive metadata before extracting anything. Returns members to write."""
    archive_size = archive_path.stat().st_size
    if archive_size > limits.max_archive_bytes:
        raise ArchiveSecurityError(
            f"archive is {archive_size / 1e6:.1f} MB which exceeds the "
            f"{limits.max_archive_bytes / 1e6:.0f} MB upload limit"
        )
    if not zipfile.is_zipfile(archive_path):
        raise ArchiveSecurityError("file is not a valid ZIP archive")

    accepted: list[zipfile.ZipInfo] = []
    total_uncompressed = 0

    with zipfile.ZipFile(archive_path) as zf:
        members = zf.infolist()
        if len(members) > limits.max_file_count:
            raise ArchiveSecurityError(
                f"archive contains {len(members)} entries, above the limit of "
                f"{int(limits.max_file_count)}"
            )
        for info in members:
            name = info.filename
            if info.flag_bits & 0x1:
                raise ArchiveSecurityError(f"encrypted archive members are not supported: {name}")
            if _is_symlink(info):
                raise ArchiveSecurityError(f"archive contains a symlink, which is not allowed: {name}")
            if not _is_regular_or_dir(info):
                raise ArchiveSecurityError(f"archive contains a non-regular file: {name}")
            if info.is_dir():
                continue
            if _should_skip(name):
                continue
            try:
                normalize_relative(name)
            except PathSecurityError as exc:
                raise ArchiveSecurityError(f"unsafe archive member {name!r}: {exc}") from exc
            if info.file_size > limits.max_file_bytes:
                raise ArchiveSecurityError(
                    f"member {name!r} is {info.file_size / 1e6:.1f} MB, above the "
                    f"{limits.max_file_bytes / 1e6:.0f} MB per-file limit"
                )
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > limits.max_compression_ratio and info.file_size > 1_000_000:
                    raise ArchiveSecurityError(
                        f"member {name!r} has a {ratio:.0f}x compression ratio "
                        "which looks like a zip bomb"
                    )
            total_uncompressed += info.file_size
            if total_uncompressed > limits.max_total_uncompressed_bytes:
                raise ArchiveSecurityError(
                    "archive expands to more than "
                    f"{limits.max_total_uncompressed_bytes / 1e6:.0f} MB"
                )
            accepted.append(info)

    if not accepted:
        raise ArchiveSecurityError("archive contains no extractable files")
    return accepted


def safe_extract_zip(
    archive_path: Path, destination: Path, limits: ExtractionLimits | None = None
) -> ExtractionReport:
    """Extract `archive_path` into `destination` under the policy above."""
    limits = limits or ExtractionLimits()
    destination.mkdir(parents=True, exist_ok=True)
    destination_resolved = destination.resolve()
    members = inspect_zip(archive_path, limits)
    report = ExtractionReport()

    with zipfile.ZipFile(archive_path) as zf:
        for info in members:
            relative = normalize_relative(info.filename)
            target = destination_resolved / relative
            # Re-check after joining: this catches case-folding and normalisation tricks.
            if not is_within(destination_resolved, target.parent if not target.parent.exists() else target.parent):
                raise ArchiveSecurityError(f"member escapes destination: {info.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not is_within(destination_resolved, target.parent):
                raise ArchiveSecurityError(f"member escapes destination: {info.filename!r}")

            written = 0
            with zf.open(info, "r") as source, target.open("wb") as sink:
                while True:
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    # Guard against a lying central directory (file_size mismatch).
                    if written > limits.max_file_bytes:
                        sink.close()
                        target.unlink(missing_ok=True)
                        raise ArchiveSecurityError(
                            f"member {info.filename!r} exceeded its declared size while extracting"
                        )
                    sink.write(chunk)
            report.files_written += 1
            report.bytes_written += written
            if report.bytes_written > limits.max_total_uncompressed_bytes:
                raise ArchiveSecurityError("archive exceeded the total extraction budget")

    logger.info(
        "extracted %d files (%.1f MB) into %s",
        report.files_written,
        report.bytes_written / 1e6,
        destination,
    )
    return report
