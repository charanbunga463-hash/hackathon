"""Dependency + framework detection from manifests and imports."""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from ..models.project import DependencyInfo
from ..utils.filesystem import iter_files, read_text, relative_posix

REQUIREMENT_LINE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._\-]*)\s*(?P<extras>\[[^\]]*\])?\s*(?P<spec>[<>=!~^].*)?\s*$"
)

FRAMEWORK_PACKAGES = {
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "starlette": "starlette",
    "sanic": "sanic",
    "aiohttp": "aiohttp",
    "tornado": "tornado",
    "litestar": "litestar",
    "quart": "quart",
    "bottle": "bottle",
}

TEST_PACKAGES = {"pytest": "pytest", "unittest": "unittest", "nose": "nose"}


def parse_requirements_txt(path: Path, relative: str) -> list[DependencyInfo]:
    deps: list[DependencyInfo] = []
    for raw in read_text(path).splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = REQUIREMENT_LINE.match(line)
        if match:
            deps.append(
                DependencyInfo(
                    name=match.group("name").lower(),
                    specifier=(match.group("spec") or "").strip() or None,
                    source_file=relative,
                )
            )
    return deps


def parse_pyproject(path: Path, relative: str) -> tuple[list[DependencyInfo], str | None]:
    deps: list[DependencyInfo] = []
    python_hint: str | None = None
    try:
        data = tomllib.loads(read_text(path))
    except (tomllib.TOMLDecodeError, ValueError):
        return deps, None

    project = data.get("project") or {}
    python_hint = project.get("requires-python")
    for entry in project.get("dependencies") or []:
        match = REQUIREMENT_LINE.match(str(entry))
        if match:
            deps.append(
                DependencyInfo(
                    name=match.group("name").lower(),
                    specifier=(match.group("spec") or "").strip() or None,
                    source_file=relative,
                )
            )

    poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
    for name, spec in poetry.items():
        if name.lower() == "python":
            python_hint = python_hint or (spec if isinstance(spec, str) else None)
            continue
        deps.append(
            DependencyInfo(
                name=str(name).lower(),
                specifier=spec if isinstance(spec, str) else None,
                source_file=relative,
            )
        )
    return deps, python_hint


def parse_package_json(path: Path, relative: str) -> list[DependencyInfo]:
    import json

    try:
        data = json.loads(read_text(path))
    except (ValueError, TypeError):
        return []
    deps: list[DependencyInfo] = []
    for section in ("dependencies", "devDependencies"):
        for name, spec in (data.get(section) or {}).items():
            deps.append(DependencyInfo(name=str(name), specifier=str(spec), source_file=relative))
    return deps


def collect_imports(root: Path, limit: int = 400) -> set[str]:
    """Top-level module names imported anywhere in the project."""
    modules: set[str] = set()
    scanned = 0
    for path in iter_files(root):
        if path.suffix != ".py" or scanned >= limit:
            continue
        scanned += 1
        source = read_text(path)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            for match in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", source, re.M):
                modules.add(match.group(1))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.add(node.module.split(".")[0])
    return modules


def analyze_dependencies(root: Path) -> tuple[list[DependencyInfo], list[str], str | None]:
    """Returns (dependencies, manifest files, python version hint)."""
    deps: list[DependencyInfo] = []
    manifests: list[str] = []
    python_hint: str | None = None

    for path in iter_files(root):
        name = path.name.lower()
        relative = relative_posix(path, root)
        if name in {"requirements.txt", "requirements-dev.txt", "dev-requirements.txt"}:
            manifests.append(relative)
            deps.extend(parse_requirements_txt(path, relative))
        elif name == "pyproject.toml":
            manifests.append(relative)
            parsed, hint = parse_pyproject(path, relative)
            deps.extend(parsed)
            python_hint = python_hint or hint
        elif name == "package.json" and "node_modules" not in relative:
            manifests.append(relative)
            deps.extend(parse_package_json(path, relative))
        elif name in {"setup.cfg", "setup.py", "pytest.ini", "tox.ini", "dockerfile", "docker-compose.yml", ".env.example"}:
            manifests.append(relative)

    seen: set[str] = set()
    unique: list[DependencyInfo] = []
    for dep in deps:
        if dep.name in seen:
            continue
        seen.add(dep.name)
        unique.append(dep)
    return unique, sorted(set(manifests)), python_hint


def detect_framework(dependencies: list[DependencyInfo], imports: set[str]) -> str:
    names = {dep.name.lower() for dep in dependencies}
    lowered_imports = {i.lower() for i in imports}
    for package, framework in FRAMEWORK_PACKAGES.items():
        if package in names or package in lowered_imports:
            return framework
    return "unknown"


def detect_test_framework(dependencies: list[DependencyInfo], imports: set[str], test_files: list[str]) -> str | None:
    names = {dep.name.lower() for dep in dependencies}
    lowered = {i.lower() for i in imports}
    if "pytest" in names or "pytest" in lowered:
        return "pytest"
    if test_files:
        # pytest can run plain unittest/`test_*` files, so default to it.
        return "pytest" if "unittest" not in lowered else "unittest"
    return None


def detect_language(root: Path, dependencies: list[DependencyInfo]) -> str:
    counts: dict[str, int] = {}
    for path in iter_files(root):
        suffix = path.suffix.lower()
        if suffix in {".py", ".pyi"}:
            counts["python"] = counts.get("python", 0) + 1
        elif suffix in {".ts", ".tsx"}:
            counts["typescript"] = counts.get("typescript", 0) + 1
        elif suffix in {".js", ".jsx"}:
            counts["javascript"] = counts.get("javascript", 0) + 1
        elif suffix == ".go":
            counts["go"] = counts.get("go", 0) + 1
        elif suffix == ".java":
            counts["java"] = counts.get("java", 0) + 1
        elif suffix == ".rb":
            counts["ruby"] = counts.get("ruby", 0) + 1
    if not counts:
        return "unknown"
    return max(counts.items(), key=lambda kv: kv[1])[0]
