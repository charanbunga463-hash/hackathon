"""Path containment.

Every path that comes from a model, an archive, or an HTTP request is untrusted.
It is resolved against a project root and rejected unless it stays inside.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


class PathSecurityError(ValueError):
    """Raised when a path escapes its allowed root or is otherwise unsafe."""


# Files the repair engine must never touch, even inside the workspace.
PROTECTED_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
    ".npmrc",
    ".pypirc",
    ".netrc",
}
PROTECTED_DIRS = {".git", ".ssh", ".venv", "venv", "node_modules", "__pycache__"}
FORBIDDEN_SUFFIXES = {".exe", ".dll", ".so", ".dylib", ".pyd", ".bin", ".pem", ".key", ".p12"}


def normalize_relative(raw: str) -> str:
    """Normalise a user/model supplied relative path to posix form.

    Rejects absolute paths, drive letters, UNC paths, `..` segments and NUL bytes.
    """
    if raw is None:
        raise PathSecurityError("path is required")
    candidate = str(raw).strip().replace("\\", "/")
    if not candidate:
        raise PathSecurityError("path is empty")
    if "\x00" in candidate:
        raise PathSecurityError("path contains a NUL byte")
    if candidate.startswith("//"):
        raise PathSecurityError(f"UNC paths are not allowed: {raw!r}")
    if candidate.startswith("/"):
        raise PathSecurityError(f"absolute paths are not allowed: {raw!r}")
    if len(candidate) >= 2 and candidate[1] == ":":
        raise PathSecurityError(f"drive-qualified paths are not allowed: {raw!r}")
    pure = PurePosixPath(candidate)
    parts: list[str] = []
    for part in pure.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise PathSecurityError(f"path traversal is not allowed: {raw!r}")
        parts.append(part)
    if not parts:
        raise PathSecurityError(f"path resolves to nothing: {raw!r}")
    return "/".join(parts)


def is_within(root: Path, candidate: Path) -> bool:
    try:
        root_resolved = root.resolve()
        candidate_resolved = candidate.resolve()
    except OSError:
        return False
    return root_resolved == candidate_resolved or root_resolved in candidate_resolved.parents


def safe_join(root: Path, raw: str) -> Path:
    """Join a relative path to root and guarantee containment after resolution."""
    relative = normalize_relative(raw)
    target = (root / relative)
    # `resolve()` follows symlinks, so a symlinked escape is caught here too.
    if not is_within(root, target if target.exists() else target.parent if target.parent.exists() else root):
        raise PathSecurityError(f"path escapes the project root: {raw!r}")
    resolved_parent = (target.parent.resolve() if target.parent.exists() else None)
    if resolved_parent is not None and not is_within(root, resolved_parent):
        raise PathSecurityError(f"path escapes the project root: {raw!r}")
    if target.exists() and not is_within(root, target):
        raise PathSecurityError(f"path escapes the project root: {raw!r}")
    return target


def assert_editable(root: Path, raw: str) -> Path:
    """safe_join plus the write-side policy: no protected files, no binaries."""
    target = safe_join(root, raw)
    relative = PurePosixPath(normalize_relative(raw))
    if relative.name in PROTECTED_NAMES:
        raise PathSecurityError(f"refusing to modify a protected file: {relative}")
    for part in relative.parts[:-1]:
        if part in PROTECTED_DIRS:
            raise PathSecurityError(f"refusing to modify inside a protected directory: {part}")
    if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise PathSecurityError(f"refusing to modify a binary/credential file type: {relative.suffix}")
    if target.exists() and target.is_symlink():
        raise PathSecurityError(f"refusing to modify a symlink: {relative}")
    if target.exists() and not target.is_file():
        raise PathSecurityError(f"not a regular file: {relative}")
    return target


def relative_to_root(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return os.path.basename(str(path))
