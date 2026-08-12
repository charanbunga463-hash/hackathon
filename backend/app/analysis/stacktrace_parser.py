"""Python traceback + pytest output parsing.

Two shapes must be handled:

1. A classic CPython traceback (`File "x.py", line 3, in f`) — what you get
   from an API 500 response or captured stderr.
2. pytest's own failure report, which uses `path:line: ErrorType` and inline
   `E   ErrorType: message` lines and does *not* always emit a classic
   traceback (assertion rewriting, short tracebacks, collection errors).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..models.execution import Severity, StackFrame

CLASSIC_FRAME = re.compile(
    r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>[^\n]+)$'
)
# pytest emits two location shapes in a --tb=long block:
#   tests/test_users.py:24: in test_get_user     (a frame)
#   main.py:42: KeyError                         (the raising line)
# The path may be absolute, and on Windows it then starts with a drive letter —
# `C:\...\main.py:42: KeyError` — so the drive colon must be matched explicitly
# before the "no more colons" rule that finds the line-number separator.
PYTEST_LOCATION = re.compile(
    r"^(?P<file>(?:[A-Za-z]:)?[^\s:][^:]*\.py):(?P<line>\d+):\s*"
    r"(?:in\s+(?P<func>\S+)|(?P<exc>[A-Za-z_][A-Za-z0-9_.]*))?\s*$"
)
PYTEST_ERROR_LINE = re.compile(r"^E\s+(?P<body>.+)$")
EXCEPTION_LINE = re.compile(
    r"^(?P<type>[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Warning|Exit|Interrupt|Failure))"
    r"(?::\s*(?P<message>.*))?$"
)
PYTEST_SHORT_SUMMARY = re.compile(
    r"^(?P<outcome>FAILED|ERROR)\s+(?P<node>\S+)(?:\s+-\s+(?P<detail>.*))?$"
)
PYTEST_HEADER = re.compile(r"^_{3,}\s+(?P<name>.+?)\s+_{3,}$")
PYTEST_ERROR_HEADER = re.compile(r"^_{3,}\s+ERROR (?:at setup of |collecting )?(?P<name>.+?)\s+_{3,}$")
PYTEST_COUNTS = re.compile(
    r"(?P<count>\d+)\s+(?P<label>passed|failed|error|errors|skipped|xfailed|xpassed|warning|warnings|deselected)\b"
)
SUMMARY_DURATION = re.compile(r"\bin\s+[\d.]+\s*s(?:econds)?\b")

SEVERITY_BY_TYPE = {
    "SyntaxError": Severity.CRITICAL,
    "IndentationError": Severity.CRITICAL,
    "ImportError": Severity.CRITICAL,
    "ModuleNotFoundError": Severity.CRITICAL,
    "NameError": Severity.HIGH,
    "KeyError": Severity.HIGH,
    "TypeError": Severity.HIGH,
    "AttributeError": Severity.HIGH,
    "IndexError": Severity.HIGH,
    "ValueError": Severity.HIGH,
    "ZeroDivisionError": Severity.HIGH,
    "ValidationError": Severity.HIGH,
    "ResponseValidationError": Severity.HIGH,
    "HTTPException": Severity.MEDIUM,
    "AssertionError": Severity.MEDIUM,
    "DeprecationWarning": Severity.LOW,
}

# Frames from these paths belong to the runtime, not the project under repair.
VENDOR_MARKERS = (
    "site-packages",
    "dist-packages",
    "/usr/lib/python",
    "\\lib\\python",
    "lib/python3",
    "<frozen",
    "_pytest",
    "/pluggy/",
    "\\pluggy\\",
)


@dataclass
class ParsedTraceback:
    error_type: str = "UnknownError"
    message: str = ""
    frames: list[StackFrame] = field(default_factory=list)
    raw: str = ""

    @property
    def project_frames(self) -> list[StackFrame]:
        return [frame for frame in self.frames if frame.in_project]

    def culprit(self) -> StackFrame | None:
        """Deepest frame that belongs to the project under repair."""
        project = self.project_frames
        if project:
            return project[-1]
        return self.frames[-1] if self.frames else None


def is_vendor_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return any(marker.replace("\\", "/").lower() in normalized for marker in VENDOR_MARKERS)


def normalize_path(path: str, project_root: Path | None = None) -> str:
    """Convert an absolute runtime path back to a project-relative posix path.

    Three cases must work: a path already relative to the workspace, an absolute
    host path (pytest emits these whenever it cannot compute a relative path —
    common on Windows, where 8.3 short names in TEMP defeat its heuristic), and
    a container path from a docker run, which never exists on the host at all.
    """
    cleaned = path.strip().strip('"')
    if not cleaned:
        return cleaned
    posix = cleaned.replace("\\", "/")

    # Container paths: the host has no such directory, so resolve() cannot help.
    for prefix in ("/workspace/", "/app/"):
        if posix.startswith(prefix):
            return posix[len(prefix) :]
    if posix.startswith("./"):
        posix = posix[2:]

    if project_root is not None:
        candidate = Path(cleaned)
        if candidate.is_absolute():
            try:
                return candidate.resolve().relative_to(project_root.resolve()).as_posix()
            except (ValueError, OSError):
                pass
            # resolve() can still fail to line up (case differences, junctions),
            # so fall back to a case-insensitive prefix match on the root.
            root_posix = str(project_root.resolve()).replace("\\", "/").rstrip("/")
            if posix.lower().startswith(f"{root_posix.lower()}/"):
                return posix[len(root_posix) + 1 :]
            root_plain = str(project_root).replace("\\", "/").rstrip("/")
            if posix.lower().startswith(f"{root_plain.lower()}/"):
                return posix[len(root_plain) + 1 :]
    return posix


def severity_for(error_type: str) -> Severity:
    return SEVERITY_BY_TYPE.get(error_type, Severity.HIGH)


def frame_in_project(raw_path: str, normalized: str, project_root: Path | None) -> bool:
    """A frame belongs to the project only if it resolves inside the workspace.

    Marker matching alone is not enough: a stdlib path like
    `C:\\Python314\\Lib\\concurrent\\futures\\_base.py` contains none of the
    usual vendor markers. Existence inside the workspace is the real test.
    """
    if is_vendor_path(raw_path):
        return False
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        # Still absolute after normalisation: it is not under the workspace.
        return False
    if project_root is None:
        return True
    return (project_root / normalized).exists()


def parse_traceback(text: str, project_root: Path | None = None) -> ParsedTraceback:
    """Parse either a classic traceback or a pytest failure block."""
    result = ParsedTraceback(raw=text or "")
    if not text:
        return result

    lines = text.splitlines()
    frames: list[StackFrame] = []

    for index, line in enumerate(lines):
        classic = CLASSIC_FRAME.match(line)
        if classic:
            raw_path = classic.group("file")
            normalized = normalize_path(raw_path, project_root)
            code = lines[index + 1].strip() if index + 1 < len(lines) else None
            frames.append(
                StackFrame(
                    file=normalized,
                    line=int(classic.group("line")),
                    function=classic.group("func").strip(),
                    code=code or None,
                    in_project=frame_in_project(raw_path, normalized, project_root),
                )
            )
            continue
        pytest_loc = PYTEST_LOCATION.match(line)
        if pytest_loc:
            raw_path = pytest_loc.group("file")
            normalized = normalize_path(raw_path, project_root)
            frames.append(
                StackFrame(
                    file=normalized,
                    line=int(pytest_loc.group("line")),
                    function=(pytest_loc.group("func") or None),
                    code=None,
                    in_project=frame_in_project(raw_path, normalized, project_root),
                )
            )

    result.frames = frames
    error_type, message = extract_exception(lines)
    result.error_type = error_type
    result.message = message
    return result


def extract_exception(lines: list[str]) -> tuple[str, str]:
    """Find the final `ErrorType: message`, preferring pytest `E ` lines."""
    candidates: list[tuple[str, str]] = []

    for line in lines:
        error_line = PYTEST_ERROR_LINE.match(line)
        body = error_line.group("body").strip() if error_line else line.strip()
        match = EXCEPTION_LINE.match(body)
        if match:
            candidates.append((match.group("type"), (match.group("message") or "").strip()))
            continue
        # `E   assert 1 == 2` — pytest's rewritten assertion form.
        if error_line and body.startswith("assert "):
            candidates.append(("AssertionError", body))

    if not candidates:
        return "UnknownError", ""
    # The last one is the actual raised exception; earlier ones are context.
    error_type, message = candidates[-1]
    # `fastapi.exceptions.ResponseValidationError` -> keep the leaf name.
    if "." in error_type:
        error_type = error_type.rsplit(".", 1)[-1]
    return error_type, message


def split_pytest_failures(stdout: str) -> list[tuple[str, str]]:
    """Split the FAILURES/ERRORS section into (node-ish name, block) pairs."""
    lines = stdout.splitlines()
    blocks: list[tuple[str, str]] = []
    current_name: str | None = None
    current: list[str] = []
    in_failures = False

    for line in lines:
        if re.match(r"^=+ (FAILURES|ERRORS) =+$", line.strip()):
            in_failures = True
            continue
        if re.match(r"^=+ (short test summary info|warnings summary|slowest) ", line.strip()):
            if current_name is not None:
                blocks.append((current_name, "\n".join(current)))
                current_name, current = None, []
            in_failures = False
            continue
        if not in_failures:
            continue
        header = PYTEST_ERROR_HEADER.match(line.strip()) or PYTEST_HEADER.match(line.strip())
        if header:
            if current_name is not None:
                blocks.append((current_name, "\n".join(current)))
            current_name = header.group("name").strip()
            current = []
            continue
        if current_name is not None:
            current.append(line)

    if current_name is not None:
        blocks.append((current_name, "\n".join(current)))
    return blocks


def parse_short_summary(stdout: str) -> list[dict]:
    """Parse `FAILED tests/test_x.py::test_y - KeyError: 'username'` lines."""
    entries: list[dict] = []
    in_summary = False
    for line in stdout.splitlines():
        stripped = line.strip()
        if re.match(r"^=+ short test summary info =+$", stripped):
            in_summary = True
            continue
        if in_summary and re.match(r"^=+ .* =+$", stripped):
            break
        if not in_summary:
            continue
        match = PYTEST_SHORT_SUMMARY.match(stripped)
        if match:
            entries.append(
                {
                    "outcome": match.group("outcome").lower(),
                    "node_id": match.group("node"),
                    "detail": (match.group("detail") or "").strip(),
                }
            )
    return entries


def parse_counts(stdout: str) -> dict[str, int]:
    """Read pytest's final tally.

    Two shapes, depending on verbosity and terminal width:
        ==== 2 failed, 6 passed in 0.31s ====
        2 failed, 4 passed, 1 warning in 1.03s
    Both end with `in <duration>s`, which is the reliable anchor.
    """
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
    summary_lines = [
        line for line in stdout.splitlines()
        if SUMMARY_DURATION.search(line) and PYTEST_COUNTS.search(line)
    ]
    if not summary_lines:
        return counts
    for match in PYTEST_COUNTS.finditer(summary_lines[-1]):
        label = match.group("label")
        count = int(match.group("count"))
        if label in {"error", "errors"}:
            counts["errors"] = count
        elif label in {"warning", "warnings", "deselected"}:
            continue
        elif label in counts:
            counts[label] = count
    return counts


def extract_collection_error(stdout: str, stderr: str) -> str | None:
    """Detect the "tests could not even be imported" case."""
    combined = f"{stdout}\n{stderr}"
    markers = (
        "ERROR collecting",
        "ImportError while importing test module",
        "INTERNALERROR",
        "no tests ran",
    )
    for marker in markers:
        if marker in combined:
            index = combined.find(marker)
            return combined[index : index + 1500].strip()
    return None
