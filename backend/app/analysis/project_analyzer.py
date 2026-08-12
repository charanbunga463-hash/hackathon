"""Static project analysis.

Produces the `ProjectMetadata` the whole system reasons from. Nothing here
imports or executes project code — analysis is pure parsing.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..models.project import ProjectMetadata, TestFileInfo
from ..utils.filesystem import iter_files, read_text, relative_posix
from ..utils.timestamps import utcnow_iso
from .api_analyzer import discover_routes
from .dependency_analyzer import (
    analyze_dependencies,
    collect_imports,
    detect_framework,
    detect_language,
    detect_test_framework,
)

ENTRY_POINT_CANDIDATES = [
    "main.py", "app.py", "app/main.py", "src/main.py", "api.py", "server.py",
    "application.py", "asgi.py", "wsgi.py", "run.py", "src/app.py", "app/app.py",
]


def is_test_file(relative: str) -> bool:
    normalized = relative.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    if not name.endswith(".py"):
        return False
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
        or "/tests/" in f"/{normalized}"
        or normalized.startswith("tests/")
    )


def collect_test_functions(source: str) -> list[str]:
    names: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            names.append(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test"):
                    names.append(f"{node.name}::{child.name}")
    return names


def find_entry_point(root: Path, app_files: list[str], source_files: list[str]) -> str | None:
    """Prefer a file that actually constructs the ASGI app."""
    if app_files:
        # Shallowest path wins: `main.py` beats `src/deep/other.py`.
        return sorted(app_files, key=lambda p: (p.count("/"), len(p)))[0]
    lookup = {path.lower() for path in source_files}
    for candidate in ENTRY_POINT_CANDIDATES:
        if candidate in lookup:
            return candidate
    for path in source_files:
        if Path(path).name in {"main.py", "app.py"}:
            return path
    return source_files[0] if source_files else None


def analyze_project(root: Path) -> ProjectMetadata:
    """Full static analysis of a workspace."""
    metadata = ProjectMetadata(analyzed_at=utcnow_iso())
    if not root.exists():
        metadata.notes.append("workspace directory does not exist")
        return metadata

    source_files: list[str] = []
    test_files: list[str] = []
    test_details: list[TestFileInfo] = []
    total_size = 0
    file_count = 0

    for path in iter_files(root):
        relative = relative_posix(path, root)
        try:
            total_size += path.stat().st_size
        except OSError:
            pass
        file_count += 1
        name = path.name.lower()
        if name == "dockerfile":
            metadata.has_dockerfile = True
        if name.startswith("readme"):
            metadata.has_readme = True
        if path.suffix != ".py":
            continue
        source_files.append(relative)
        if is_test_file(relative):
            test_files.append(relative)
            names = collect_test_functions(read_text(path))
            test_details.append(
                TestFileInfo(path=relative, test_count=len(names), test_names=names)
            )

    metadata.file_count = file_count
    metadata.total_size_bytes = total_size
    metadata.source_files = sorted(source_files)
    metadata.test_files = sorted(test_files)
    metadata.test_details = sorted(test_details, key=lambda t: t.path)

    dependencies, manifests, python_hint = analyze_dependencies(root)
    metadata.dependencies = dependencies
    metadata.config_files = manifests
    metadata.python_version_hint = python_hint

    imports = collect_imports(root)
    metadata.language = detect_language(root, dependencies)
    metadata.framework = detect_framework(dependencies, imports)
    metadata.test_framework = detect_test_framework(dependencies, imports, metadata.test_files)

    routes, route_info = discover_routes(root)
    metadata.routes = routes
    app_files = route_info.get("app_files") or []
    metadata.entry_point = find_entry_point(root, app_files, metadata.source_files)
    if metadata.entry_point:
        metadata.app_object = (route_info.get("app_objects") or {}).get(metadata.entry_point, "app")

    if not metadata.routes:
        metadata.notes.append("no HTTP routes were discovered by static analysis")
    if not metadata.test_files:
        metadata.notes.append("no test files were discovered; API mode is the only failure detector available")
    if metadata.framework == "unknown" and metadata.language == "python":
        metadata.notes.append("no known web framework detected in dependencies or imports")
    if metadata.language != "python":
        metadata.notes.append(
            f"detected language is '{metadata.language}'; repair support currently targets Python projects"
        )

    return metadata


def build_file_tree(root: Path, max_entries: int = 3000) -> list[dict]:
    """Nested file tree for the code viewer."""
    from ..utils.filesystem import is_ignored_dir

    def walk(directory: Path, depth: int = 0) -> list[dict]:
        if depth > 12:
            return []
        nodes: list[dict] = []
        try:
            entries = sorted(
                directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
            )
        except OSError:
            return []
        for entry in entries:
            if entry.is_dir():
                if is_ignored_dir(entry.name):
                    continue
                children = walk(entry, depth + 1)
                nodes.append(
                    {
                        "name": entry.name,
                        "path": relative_posix(entry, root),
                        "type": "directory",
                        "size": 0,
                        "children": children,
                    }
                )
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                nodes.append(
                    {
                        "name": entry.name,
                        "path": relative_posix(entry, root),
                        "type": "file",
                        "size": size,
                    }
                )
            if len(nodes) > max_entries:
                break
        return nodes

    return walk(root)


LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".pyi": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".json": "json", ".yaml": "yaml",
    ".yml": "yaml", ".toml": "toml", ".md": "markdown", ".html": "html",
    ".css": "css", ".sql": "sql", ".sh": "bash", ".txt": "plaintext",
    ".cfg": "ini", ".ini": "ini",
}


def language_for(path: str) -> str:
    return LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower(), "plaintext")
