"""Filesystem helpers used across analysis, patching and persistence."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterable, Iterator

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
    "dist",
    "build",
    ".next",
    ".tox",
    "site-packages",
    ".egg-info",
}

TEXT_EXTENSIONS = {
    ".py", ".pyi", ".txt", ".md", ".rst", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".env", ".sh", ".bat", ".ps1", ".js", ".jsx", ".ts", ".tsx", ".html",
    ".css", ".sql", ".xml", ".csv", ".lock", ".gitignore", ".dockerignore", "",
}

BINARY_SNIFF_BYTES = 4096


def is_ignored_dir(name: str) -> bool:
    return name in IGNORED_DIRS or name.endswith(".egg-info")


def iter_files(root: Path, *, max_files: int = 20000) -> Iterator[Path]:
    """Walk a project tree, skipping vendor/VCS/cache directories."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not is_ignored_dir(d))
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            count += 1
            if count > max_files:
                return
            yield path


def relative_posix(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(BINARY_SNIFF_BYTES)
    except OSError:
        return True
    if b"\x00" in chunk:
        return True
    return False


def read_text(path: Path, *, max_bytes: int = 2_000_000) -> str:
    """Read a text file defensively; returns '' for unreadable/binary files."""
    try:
        if path.stat().st_size > max_bytes:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                return handle.read(max_bytes)
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def write_text_atomic(path: Path, content: str) -> None:
    """Write via a temp file in the same directory, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, payload) -> None:
    write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def dir_size_bytes(root: Path) -> int:
    total = 0
    for path in iter_files(root):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def count_files(root: Path) -> int:
    return sum(1 for _ in iter_files(root))


def rmtree(path: Path) -> None:
    """Remove a tree, tolerating Windows read-only files."""

    def _on_error(func, target, _exc_info):  # pragma: no cover - platform specific
        try:
            os.chmod(target, 0o700)
            func(target)
        except OSError:
            pass

    if path.exists():
        shutil.rmtree(path, onerror=_on_error)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def collapse_single_root(directory: Path) -> None:
    """Archives often nest everything under one folder; flatten that."""
    entries = [p for p in directory.iterdir() if p.name not in {"__MACOSX"}]
    if len(entries) != 1 or not entries[0].is_dir():
        return
    inner = entries[0]
    for child in list(inner.iterdir()):
        target = directory / child.name
        if target.exists():
            return
        shutil.move(str(child), str(target))
    rmtree(inner)


def slice_lines(content: str, start: int, end: int) -> str:
    """1-indexed, inclusive line slice."""
    lines = content.splitlines()
    start = max(1, start)
    end = min(len(lines), end)
    if start > len(lines):
        return ""
    return "\n".join(lines[start - 1 : end])


def numbered_slice(content: str, start: int, end: int) -> str:
    lines = content.splitlines()
    start = max(1, start)
    end = min(len(lines), end)
    width = len(str(end))
    return "\n".join(
        f"{i:>{width}} | {lines[i - 1]}" for i in range(start, end + 1)
    )


def unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
