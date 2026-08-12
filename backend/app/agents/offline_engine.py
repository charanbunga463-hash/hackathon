"""Deterministic rule engine — the fallback when no OpenAI key is configured.

This is NOT the AI. It is a small, honest, rule-based debugger that covers the
common Python API failure modes so the full detect → diagnose → patch → verify →
retry pipeline can be exercised (and tested in CI) without credentials.

Everything it produces is tagged `reasoning_engine="deterministic-offline"` and
the UI labels it as such. It never claims to be model output.

Its rules are deliberately conservative: when no rule matches with confidence,
it returns a grounded diagnosis with NO patch and says plainly that offline mode
cannot generate this fix. Guessing would violate the product's core promise.
"""

from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from ..models.diagnosis import (
    AffectedFile,
    DiagnosisResult,
    EvidenceItem,
    EvidenceKind,
    Hypothesis,
    RepairPlan,
    RepairPlanStep,
)
from ..models.execution import NormalizedFailure, Severity
from ..models.patch import EditOperation, FileEdit, PatchProposal
from ..models.project import ProjectMetadata
from ..patches.patch_parser import new_patch_id
from ..utils.filesystem import read_text
from ..utils.logging import get_logger

logger = get_logger(__name__)

ENGINE_NAME = "deterministic-offline"


@dataclass
class RuleOutcome:
    root_cause: str
    summary: str
    confidence: float
    edits: list[FileEdit]
    evidence: list[EvidenceItem]
    title: str
    explanation: str
    hypotheses: list[Hypothesis]
    strategy: str = ""


def _line_at(workspace: Path, relative: str | None, line: int | None) -> str:
    if not relative or not line:
        return ""
    target = workspace / relative
    if not target.exists() or not target.is_file():
        return ""
    lines = read_text(target).splitlines()
    if 1 <= line <= len(lines):
        return lines[line - 1]
    return ""


def _find_unique_anchor(content: str, snippet: str, line: int | None) -> str | None:
    """Grow an anchor until it occurs exactly once in the file."""
    if not snippet:
        return None
    if content.count(snippet) == 1:
        return snippet
    lines = content.splitlines()
    if not line or not (1 <= line <= len(lines)):
        return None
    for radius in range(0, 6):
        start = max(0, line - 1 - radius)
        end = min(len(lines), line + radius)
        candidate = "\n".join(lines[start:end])
        if candidate and content.count(candidate) == 1:
            return candidate
    return None


def _looks_like_dict_key(value: str) -> bool:
    """Filter out things that are strings in a `.get()` but not dict keys.

    `@app.get("/health")` parses identically to `record.get("health")`, so a
    naive sweep collects every route path as a candidate key. Route paths and
    other non-identifier strings are never what a KeyError is about.
    """
    return bool(value) and not value.startswith("/") and value.isidentifier()


def _dict_keys_in_file(workspace: Path, relative: str) -> list[str]:
    """Every string key used in a dict literal or a dict `.get()` in the file."""
    target = workspace / relative
    if not target.exists():
        return []
    source = read_text(target)
    keys: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [
            key
            for key in re.findall(r"[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*:", source)
            if _looks_like_dict_key(key)
        ]
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    if _looks_like_dict_key(key.value):
                        keys.append(key.value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            # Skip decorator-style calls on an app/router object.
            owner = node.func.value
            owner_name = owner.id if isinstance(owner, ast.Name) else None
            if owner_name in {"app", "router", "api", "client", "requests", "httpx"}:
                continue
            for arg in node.args[:1]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if _looks_like_dict_key(arg.value):
                        keys.append(arg.value)
    return list(dict.fromkeys(keys))


def _all_dict_keys(workspace: Path, metadata: ProjectMetadata) -> dict[str, list[str]]:
    return {
        relative: _dict_keys_in_file(workspace, relative)
        for relative in metadata.source_files[:60]
        if relative.endswith(".py")
    }


def _closest(candidates: list[str], target: str, cutoff: float = 0.55) -> str | None:
    matches = difflib.get_close_matches(target, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def _evidence(kind: EvidenceKind, source: str, detail: str, line: int | None = None, excerpt: str = "") -> EvidenceItem:
    return EvidenceItem(
        kind=kind, source=source, detail=detail, line=line, excerpt=excerpt or None, verified=True
    )


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def rule_key_error(
    workspace: Path, metadata: ProjectMetadata, failure: NormalizedFailure
) -> RuleOutcome | None:
    """`KeyError: 'username'` — the code reads a key the data does not have."""
    if failure.error_type != "KeyError" or not failure.file:
        return None
    missing = failure.message.strip().strip("\"'")
    if not missing:
        return None

    content = read_text(workspace / failure.file)
    if not content:
        return None
    source_line = _line_at(workspace, failure.file, failure.line)

    # Which keys DO exist? Prefer keys defined in the same file, then project-wide.
    local_keys = _dict_keys_in_file(workspace, failure.file)
    candidates = [key for key in local_keys if key != missing]
    replacement = _closest(candidates, missing)
    origin_file = failure.file
    if replacement is None:
        for relative, keys in _all_dict_keys(workspace, metadata).items():
            found = _closest([k for k in keys if k != missing], missing)
            if found:
                replacement, origin_file = found, relative
                break
    if replacement is None:
        return None

    # Match the SUBSCRIPT form first: in `"username": user["username"]` only the
    # second occurrence is the lookup that raised. Rewriting the response key
    # instead would silently change the API contract.
    quoted = next(
        (f"[{q}{missing}{q}]" for q in ('"', "'") if f"[{q}{missing}{q}]" in source_line),
        None,
    )
    if quoted is None:
        quoted = next(
            (f"{q}{missing}{q}" for q in ('"', "'") if f"{q}{missing}{q}" in source_line), None
        )
    if quoted is None:
        return None

    anchor = _find_unique_anchor(content, source_line.strip(), failure.line)
    if anchor is None:
        return None
    new_text = anchor.replace(quoted, quoted.replace(missing, replacement), 1)
    if new_text == anchor:
        return None

    return RuleOutcome(
        root_cause=(
            f"{failure.file}:{failure.line} reads the dictionary key '{missing}', but the "
            f"records it operates on are built with the key '{replacement}' "
            f"({origin_file}). The subscript therefore raises KeyError on every call."
        ),
        summary=(
            f"{failure.endpoint or failure.test or 'The failing code path'} raises "
            f"KeyError: '{missing}' because that key does not exist on the data."
        ),
        confidence=0.9 if origin_file == failure.file else 0.78,
        edits=[
            FileEdit(
                path=failure.file,
                operation=EditOperation.REPLACE,
                old=anchor,
                new=new_text,
                line_hint=failure.line,
                reason=f"read the '{replacement}' key that the data actually has",
            )
        ],
        evidence=[
            _evidence(
                EvidenceKind.STACK_TRACE,
                failure.file,
                f"KeyError: '{missing}' is raised here",
                failure.line,
                source_line.strip(),
            ),
            _evidence(
                EvidenceKind.SOURCE_CODE,
                origin_file,
                f"the data structure defines the key '{replacement}', not '{missing}'",
                None,
                ", ".join(local_keys[:8]),
            ),
        ],
        title=f"Use the '{replacement}' key instead of '{missing}'",
        explanation=(
            f"The records are created with '{replacement}' as the key (see {origin_file}), "
            f"but {failure.file}:{failure.line} looks up '{missing}'. Reading the key that "
            "exists resolves the KeyError without changing any behaviour."
        ),
        hypotheses=[
            Hypothesis(
                statement=f"the data is missing the '{missing}' key for this record only",
                confidence=0.15,
                supporting_evidence=[],
                status="rejected",
            ),
            Hypothesis(
                statement=f"the code should read '{replacement}', which is the key actually stored",
                confidence=0.9,
                supporting_evidence=[origin_file],
                status="supported",
            ),
        ],
        strategy=f"rename the key access from '{missing}' to '{replacement}'",
    )


def rule_attribute_error(
    workspace: Path, metadata: ProjectMetadata, failure: NormalizedFailure
) -> RuleOutcome | None:
    """`AttributeError: 'X' object has no attribute 'y'`."""
    if failure.error_type != "AttributeError" or not failure.file:
        return None
    match = re.search(r"'([^']+)' object has no attribute '([^']+)'", failure.message)
    if not match:
        match = re.search(r"module '([^']+)' has no attribute '([^']+)'", failure.message)
    if not match:
        return None
    owner, attribute = match.group(1), match.group(2)

    content = read_text(workspace / failure.file)
    source_line = _line_at(workspace, failure.file, failure.line)
    if not content or not source_line:
        return None

    candidates = _class_attributes(workspace, metadata, owner.split(".")[-1])
    replacement = _closest([c for c in candidates if c != attribute], attribute)
    if replacement is None:
        return None

    anchor = _find_unique_anchor(content, source_line.strip(), failure.line)
    if anchor is None:
        return None
    new_text = re.sub(rf"\.{re.escape(attribute)}\b", f".{replacement}", anchor, count=1)
    if new_text == anchor:
        return None

    return RuleOutcome(
        root_cause=(
            f"{failure.file}:{failure.line} accesses `.{attribute}` on a `{owner}`, which "
            f"defines `{replacement}` instead."
        ),
        summary=f"AttributeError: '{owner}' has no attribute '{attribute}'.",
        confidence=0.8,
        edits=[
            FileEdit(
                path=failure.file,
                operation=EditOperation.REPLACE,
                old=anchor,
                new=new_text,
                line_hint=failure.line,
                reason=f"use the attribute '{replacement}' that {owner} actually defines",
            )
        ],
        evidence=[
            _evidence(
                EvidenceKind.STACK_TRACE,
                failure.file,
                f"AttributeError raised accessing .{attribute}",
                failure.line,
                source_line.strip(),
            ),
            _evidence(
                EvidenceKind.SOURCE_CODE,
                owner,
                f"{owner} defines: {', '.join(candidates[:10])}",
            ),
        ],
        title=f"Use `.{replacement}` instead of `.{attribute}`",
        explanation=(
            f"`{owner}` defines `{replacement}`; `{attribute}` does not exist on it, so the "
            "attribute access raises AttributeError."
        ),
        hypotheses=[
            Hypothesis(
                statement=f"`{owner}` should gain a new `{attribute}` attribute",
                confidence=0.2,
                supporting_evidence=[],
                status="rejected",
            )
        ],
        strategy=f"rename the attribute access to `{replacement}`",
    )


def _class_attributes(workspace: Path, metadata: ProjectMetadata, class_name: str) -> list[str]:
    attributes: list[str] = []
    for relative in metadata.source_files[:60]:
        if not relative.endswith(".py"):
            continue
        source = read_text(workspace / relative)
        if class_name not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for child in node.body:
                    if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                        attributes.append(child.target.id)
                    elif isinstance(child, ast.Assign):
                        for target in child.targets:
                            if isinstance(target, ast.Name):
                                attributes.append(target.id)
                    elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        attributes.append(child.name)
    return list(dict.fromkeys(attributes))


def rule_name_error(
    workspace: Path, metadata: ProjectMetadata, failure: NormalizedFailure
) -> RuleOutcome | None:
    """`NameError: name 'x' is not defined` — usually a typo on a real symbol."""
    if failure.error_type != "NameError" or not failure.file:
        return None
    match = re.search(r"name '([^']+)' is not defined", failure.message)
    if not match:
        return None
    missing = match.group(1)

    from ..analysis.code_search import extract_symbols

    content = read_text(workspace / failure.file)
    source_line = _line_at(workspace, failure.file, failure.line)
    if not content or not source_line:
        return None
    names = [symbol.name for symbol in extract_symbols(content, failure.file)]
    names += re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", content, re.M)
    replacement = _closest([n for n in dict.fromkeys(names) if n != missing], missing)
    if replacement is None:
        return None

    anchor = _find_unique_anchor(content, source_line.strip(), failure.line)
    if anchor is None:
        return None
    new_text = re.sub(rf"\b{re.escape(missing)}\b", replacement, anchor, count=1)
    if new_text == anchor:
        return None

    return RuleOutcome(
        root_cause=f"{failure.file}:{failure.line} references `{missing}`, which is never defined; the defined symbol is `{replacement}`.",
        summary=f"NameError: `{missing}` is not defined.",
        confidence=0.75,
        edits=[
            FileEdit(
                path=failure.file, operation=EditOperation.REPLACE, old=anchor, new=new_text,
                line_hint=failure.line, reason=f"reference the defined symbol `{replacement}`",
            )
        ],
        evidence=[
            _evidence(EvidenceKind.STACK_TRACE, failure.file,
                      f"NameError on `{missing}`", failure.line, source_line.strip()),
            _evidence(EvidenceKind.SOURCE_CODE, failure.file,
                      f"`{replacement}` is defined in this module; `{missing}` is not"),
        ],
        title=f"Reference `{replacement}` instead of `{missing}`",
        explanation=f"`{missing}` does not exist in {failure.file}. `{replacement}` is the defined symbol.",
        hypotheses=[],
        strategy=f"correct the symbol name to `{replacement}`",
    )


NUMERIC_TYPE_ERROR = re.compile(
    r"unsupported operand type\(s\) for ([^:]+): '(\w+)' and '(\w+)'"
)
MULTIPLY_SEQUENCE = re.compile(r"can't multiply sequence by non-int")


def rule_numeric_coercion(
    workspace: Path, metadata: ProjectMetadata, failure: NormalizedFailure
) -> RuleOutcome | None:
    """A string flowing into arithmetic: `'12' * 3`, `1 + '2'` and friends."""
    if failure.error_type != "TypeError" or not failure.file:
        return None
    is_numeric = bool(NUMERIC_TYPE_ERROR.search(failure.message)) or bool(
        MULTIPLY_SEQUENCE.search(failure.message)
    )
    if not is_numeric:
        return None

    content = read_text(workspace / failure.file)
    source_line = _line_at(workspace, failure.file, failure.line)
    if not content or not source_line:
        return None

    # Find the subscript/name on the line that is the string operand. A dict
    # subscript with a quoted key is by far the most common shape.
    subscripts = re.findall(r"([A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]+\])+)", source_line)
    if not subscripts:
        return None

    string_keys = _string_valued_keys(workspace, metadata)
    target_expr = None
    for expression in subscripts:
        key_match = re.search(r"\[[\"']([^\"']+)[\"']\]", expression)
        if key_match and key_match.group(1) in string_keys:
            target_expr = expression
            break
    if target_expr is None:
        target_expr = subscripts[0]

    numeric_call = "float" if "." in _sample_value(workspace, metadata, target_expr) else "int"
    anchor = _find_unique_anchor(content, source_line.strip(), failure.line)
    if anchor is None:
        return None
    new_text = anchor.replace(target_expr, f"{numeric_call}({target_expr})", 1)
    if new_text == anchor:
        return None

    return RuleOutcome(
        root_cause=(
            f"{failure.file}:{failure.line} performs arithmetic on `{target_expr}`, which holds a "
            f"string rather than a number, so the operation raises TypeError."
        ),
        summary=f"TypeError in arithmetic: {failure.message}",
        confidence=0.72,
        edits=[
            FileEdit(
                path=failure.file, operation=EditOperation.REPLACE, old=anchor, new=new_text,
                line_hint=failure.line,
                reason=f"coerce {target_expr} to {numeric_call} before the arithmetic",
            )
        ],
        evidence=[
            _evidence(EvidenceKind.STACK_TRACE, failure.file,
                      failure.message or "TypeError raised here", failure.line, source_line.strip()),
            _evidence(EvidenceKind.SOURCE_CODE, failure.file,
                      f"`{target_expr}` is used in arithmetic but carries a string value"),
        ],
        title=f"Coerce {target_expr} to {numeric_call} before arithmetic",
        explanation=(
            f"The stored value for `{target_expr}` is a string. Converting it with "
            f"`{numeric_call}()` at the point of use fixes the TypeError without changing "
            "the stored data or the response shape."
        ),
        hypotheses=[],
        strategy="coerce the string operand to a number at the point of use",
    )


def _string_valued_keys(workspace: Path, metadata: ProjectMetadata) -> set[str]:
    """Dict keys whose literal values are strings — candidates for coercion."""
    keys: set[str] = set()
    for relative in metadata.source_files[:60]:
        if not relative.endswith(".py"):
            continue
        try:
            tree = ast.parse(read_text(workspace / relative))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant) and isinstance(key.value, str)
                        and isinstance(value, ast.Constant) and isinstance(value.value, str)
                    ):
                        keys.add(key.value)
    return keys


def _sample_value(workspace: Path, metadata: ProjectMetadata, expression: str) -> str:
    key_match = re.search(r"\[[\"']([^\"']+)[\"']\]", expression)
    if not key_match:
        return ""
    wanted = key_match.group(1)
    for relative in metadata.source_files[:60]:
        if not relative.endswith(".py"):
            continue
        try:
            tree = ast.parse(read_text(workspace / relative))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant) and key.value == wanted
                        and isinstance(value, ast.Constant)
                    ):
                        return str(value.value)
    return ""


def rule_zero_division(
    workspace: Path, metadata: ProjectMetadata, failure: NormalizedFailure
) -> RuleOutcome | None:
    """`ZeroDivisionError` — guard the denominator at the point of division."""
    if failure.error_type != "ZeroDivisionError" or not failure.file:
        return None
    content = read_text(workspace / failure.file)
    source_line = _line_at(workspace, failure.file, failure.line)
    if not content or "/" not in source_line:
        return None

    match = re.search(r"(?P<num>[^=/]+?)\s*/\s*(?P<den>[A-Za-z_][A-Za-z0-9_\.\[\]\"']*(?:\([^)]*\))?)", source_line)
    if not match:
        return None
    denominator = match.group("den").strip()
    expression = f"{match.group('num').strip()} / {denominator}"
    if expression not in source_line:
        return None

    anchor = _find_unique_anchor(content, source_line.strip(), failure.line)
    if anchor is None:
        return None
    guarded = f"{expression} if {denominator} else 0"
    new_text = anchor.replace(expression, guarded, 1)
    if new_text == anchor:
        return None

    return RuleOutcome(
        root_cause=(
            f"{failure.file}:{failure.line} divides by `{denominator}` without checking that it "
            "is non-zero, so an empty collection makes the endpoint raise ZeroDivisionError."
        ),
        summary="ZeroDivisionError: the denominator can legitimately be zero.",
        confidence=0.7,
        edits=[
            FileEdit(
                path=failure.file, operation=EditOperation.REPLACE, old=anchor, new=new_text,
                line_hint=failure.line, reason=f"return 0 when {denominator} is empty",
            )
        ],
        evidence=[
            _evidence(EvidenceKind.STACK_TRACE, failure.file,
                      "ZeroDivisionError raised at this division", failure.line, source_line.strip()),
        ],
        title=f"Guard the division against an empty {denominator}",
        explanation=(
            f"`{denominator}` is empty for this input, so the division raises. Returning 0 for "
            "the empty case keeps the endpoint's contract while removing the crash."
        ),
        hypotheses=[],
        strategy="guard the denominator",
    )


# Pydantic v2 reports a missing field in two shapes:
#   Profile(...)            ->  "plan\n  Field required [type=missing, ...]"
#   response_model failure  ->  "'loc': ('response', 'isbn'), 'msg': 'Field required'"
FIELD_REQUIRED_BLOCK = re.compile(r"(?:^|\n)\s*(\w+)\s*\n\s*Field required", re.M)
FIELD_REQUIRED_LOC = re.compile(
    r"'loc':\s*\([^)]*?'(\w+)'\s*,?\s*\)\s*,\s*'msg':\s*'Field required'"
)
PYTEST_E_PREFIX = re.compile(r"^E\s{0,4}", re.M)


def _strip_pytest_prefix(text: str) -> str:
    """pytest prefixes every line of an error block with `E   `; remove it."""
    return PYTEST_E_PREFIX.sub("", text or "")


def rule_missing_field(
    workspace: Path, metadata: ProjectMetadata, failure: NormalizedFailure
) -> RuleOutcome | None:
    """Pydantic `Field required` — a model is constructed/returned without a field."""
    if failure.error_type not in {"ValidationError", "ResponseValidationError"}:
        return None
    haystack = _strip_pytest_prefix(f"{failure.message}\n{failure.traceback}")
    names = FIELD_REQUIRED_LOC.findall(haystack) or FIELD_REQUIRED_BLOCK.findall(haystack)
    missing = next(
        (name for name in names if name not in {"Field", "required", "response", "body"}), None
    )
    if not missing:
        return None

    # A response-model violation is raised inside FastAPI, so the stack points at
    # the test rather than the handler. Resolve the handler that must change.
    target_file, target_line, _function = _handler_for_failure(
        workspace, metadata, failure, haystack
    )
    if not target_file:
        return None
    if _is_test_file(target_file, metadata) and failure.file and not _is_test_file(failure.file, metadata):
        target_file, target_line = failure.file, failure.line or target_line
    if _is_test_file(target_file, metadata):
        return None

    failure = failure.model_copy(update={"file": target_file, "line": target_line})
    content = read_text(workspace / failure.file)
    if not content:
        return None

    # Find the object construction that is missing the field, near the failure.
    # Two shapes occur in practice and they need different syntax in the fix:
    #   dict:   "author": book["author"],
    #   kwargs: email=account["email"],
    source_line = _line_at(workspace, failure.file, failure.line)
    region_start = max(1, (failure.line or 1) - 14)
    region_end = (failure.line or 1) + 14
    lines = content.splitlines()
    region = lines[region_start - 1 : region_end]

    dict_form = re.compile(r"[\"'](\w+)[\"']\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\[[\"'](\w+)[\"']\]")
    kwargs_form = re.compile(r"^\s*(\w+)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\[[\"'](\w+)[\"']\]\s*,?\s*$")

    source_var: str | None = None
    key_line_index: int | None = None
    style: str | None = None
    for index, line in enumerate(region):
        kwargs_match = kwargs_form.match(line)
        if kwargs_match:
            key_line_index, source_var, style = index, kwargs_match.group(2), "kwargs"
            continue
        dict_match = dict_form.search(line)
        if dict_match:
            key_line_index, source_var, style = index, dict_match.group(2), "dict"
    if key_line_index is None or source_var is None:
        return None

    # The field must genuinely exist on the source record, or the fix is a guess.
    if not re.search(rf"[\"']{re.escape(missing)}[\"']\s*:", content):
        return None

    anchor_line = region[key_line_index]
    anchor = _find_unique_anchor(content, anchor_line.strip(), region_start + key_line_index)
    if anchor is None:
        return None

    indent = anchor_line[: len(anchor_line) - len(anchor_line.lstrip())]
    separator = "" if anchor.rstrip().endswith(",") else ","
    addition = (
        f'{missing}={source_var}["{missing}"],'
        if style == "kwargs"
        else f'"{missing}": {source_var}["{missing}"],'
    )
    new_text = f"{anchor}{separator}\n{indent}{addition}"

    return RuleOutcome(
        root_cause=(
            f"The response built at {failure.file}:{failure.line} omits the required field "
            f"'{missing}', which the declared response model requires, so FastAPI raises a "
            "validation error before the response is sent."
        ),
        summary=f"Response validation failed: required field '{missing}' is missing.",
        confidence=0.68,
        edits=[
            FileEdit(
                path=failure.file, operation=EditOperation.REPLACE, old=anchor, new=new_text,
                line_hint=region_start + key_line_index,
                reason=f"include the required '{missing}' field in the response",
            )
        ],
        evidence=[
            _evidence(EvidenceKind.API_CONTRACT, failure.endpoint or failure.file,
                      f"the response model requires the field '{missing}'"),
            _evidence(EvidenceKind.SOURCE_CODE, failure.file,
                      f"the returned object is constructed without '{missing}'",
                      failure.line, source_line.strip()),
        ],
        title=f"Include the required '{missing}' field in the response",
        explanation=(
            f"The endpoint declares a response model that requires '{missing}', but the returned "
            f"object does not set it. The source record carries the value, so adding it satisfies "
            "the contract without changing the model."
        ),
        hypotheses=[
            Hypothesis(
                statement=f"the response model should make '{missing}' optional",
                confidence=0.25,
                supporting_evidence=[],
                status="rejected",
            )
        ],
        strategy=f"add the '{missing}' field to the returned object",
    )


STATUS_ASSERT = re.compile(r"assert\s+(\d{3})\s*==\s*(\d{3})|assert\s+response\.status_code\s*==\s*(\d{3})")


def rule_missing_http_error(
    workspace: Path, metadata: ProjectMetadata, failure: NormalizedFailure
) -> RuleOutcome | None:
    """A test expects 4xx but the handler returns 200 — a missing HTTPException."""
    if failure.error_type != "AssertionError":
        return None
    haystack = f"{failure.message}\n{failure.traceback}"
    match = re.search(r"assert\s+(?P<actual>\d{3})\s*==\s*(?P<expected>\d{3})", haystack)
    if not match:
        return None
    actual, expected = int(match.group("actual")), int(match.group("expected"))
    if actual != 200 or expected not in {400, 401, 403, 404, 409, 422}:
        return None

    # Find the handler: prefer the route named by the failing endpoint/test.
    handler_file, handler_line, handler_name = _handler_for_failure(workspace, metadata, failure, haystack)
    if not handler_file:
        return None
    content = read_text(workspace / handler_file)
    if not content:
        return None
    lines = content.splitlines()

    # Look for the "not found" path: a bare `return None` or `return` inside the handler.
    target_index = None
    for index in range(handler_line, min(len(lines), handler_line + 40)):
        stripped = lines[index].strip()
        if stripped in {"return None", "return"}:
            target_index = index
            break
        if re.match(r"^(async\s+)?def\s+", stripped) and index > handler_line + 1:
            break
    if target_index is None:
        return None

    anchor_line = lines[target_index]
    anchor = _find_unique_anchor(content, anchor_line.strip(), target_index + 1)
    if anchor is None:
        return None
    indent = anchor_line[: len(anchor_line) - len(anchor_line.lstrip())]
    detail = {404: "Not found", 400: "Bad request", 403: "Forbidden", 401: "Unauthorized",
              409: "Conflict", 422: "Unprocessable entity"}[expected]
    replacement = f'raise HTTPException(status_code={expected}, detail="{detail}")'
    new_text = anchor.replace(anchor_line.strip(), replacement, 1) if anchor == anchor_line.strip() else anchor.replace(
        anchor_line.strip(), replacement, 1
    )
    if new_text == anchor:
        return None

    edits = [
        FileEdit(
            path=handler_file, operation=EditOperation.REPLACE, old=anchor, new=new_text,
            line_hint=target_index + 1,
            reason=f"return HTTP {expected} instead of a successful empty response",
        )
    ]
    if "HTTPException" not in content:
        # The import must exist for the fix to run. Anchor on the fastapi import.
        import_match = re.search(r"^from fastapi import ([^\n]+)$", content, re.M)
        if import_match is None:
            return None
        old_import = import_match.group(0)
        edits.insert(
            0,
            FileEdit(
                path=handler_file, operation=EditOperation.REPLACE,
                old=old_import, new=f"{old_import}, HTTPException",
                line_hint=1, reason="HTTPException must be imported to be raised",
            ),
        )

    _ = indent  # indentation is preserved by anchoring on the stripped line
    return RuleOutcome(
        root_cause=(
            f"{handler_file}:{target_index + 1} returns an empty successful response when the "
            f"resource does not exist, so the endpoint answers 200 instead of {expected}."
        ),
        summary=f"The endpoint returns HTTP {actual} where the contract requires HTTP {expected}.",
        confidence=0.74,
        edits=edits,
        evidence=[
            _evidence(EvidenceKind.TEST_OUTPUT, failure.test or "test assertion",
                      f"the test asserts status {expected} but observed {actual}", None,
                      match.group(0)),
            _evidence(EvidenceKind.SOURCE_CODE, handler_file,
                      f"`{handler_name or 'the handler'}` returns None on the missing-resource path",
                      target_index + 1, anchor_line.strip()),
        ],
        title=f"Raise HTTP {expected} when the resource is missing",
        explanation=(
            f"Returning None from a FastAPI handler produces a 200 with a null body. The contract "
            f"and the test both require {expected} for a missing resource, so the handler now "
            "raises HTTPException instead."
        ),
        hypotheses=[
            Hypothesis(
                statement="the test's expected status code is wrong",
                confidence=0.1,
                supporting_evidence=[],
                status="rejected",
            )
        ],
        strategy=f"raise HTTPException({expected}) on the missing-resource path",
    )


def _is_test_file(path: str | None, metadata: ProjectMetadata) -> bool:
    if not path:
        return True
    normalized = path.replace("\\", "/")
    if normalized in {p.replace("\\", "/") for p in metadata.test_files}:
        return True
    name = normalized.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{normalized}"


def _handler_for_failure(
    workspace: Path, metadata: ProjectMetadata, failure: NormalizedFailure, haystack: str
) -> tuple[str | None, int, str | None]:
    if failure.endpoint:
        for route in metadata.routes:
            if route.signature == failure.endpoint:
                return route.file, route.line, route.function
    # Mine the requested path out of the test body: client.get("/users/999")
    requested = re.findall(r"client\.\w+\(\s*[\"']([^\"']+)[\"']", haystack)
    for path in requested:
        for route in metadata.routes:
            pattern = re.sub(r"\{[^}]+\}", r"[^/]+", route.path)
            if re.fullmatch(pattern, path):
                return route.file, route.line, route.function
    if failure.file and failure.line:
        return failure.file, failure.line, failure.function
    return None, 0, None


RULES = [
    rule_key_error,
    rule_attribute_error,
    rule_name_error,
    rule_numeric_coercion,
    rule_zero_division,
    rule_missing_field,
    rule_missing_http_error,
]


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def diagnose(
    workspace: Path, metadata: ProjectMetadata, failure: NormalizedFailure
) -> tuple[DiagnosisResult, RuleOutcome | None]:
    """Run the rules and build a grounded diagnosis, patch or not."""
    outcome: RuleOutcome | None = None
    for rule in RULES:
        try:
            outcome = rule(workspace, metadata, failure)
        except Exception as exc:  # noqa: BLE001 - a bad rule must not break the pipeline
            logger.warning("offline rule %s raised: %s", rule.__name__, exc)
            outcome = None
        if outcome is not None:
            logger.info("offline rule matched: %s", rule.__name__)
            break

    base_evidence = _baseline_evidence(workspace, failure)

    if outcome is None:
        return (
            DiagnosisResult(
                summary=(
                    f"{failure.error_type} in "
                    f"{failure.endpoint or failure.test or failure.file or 'the project'}: "
                    f"{failure.message}".strip()
                ),
                root_cause=(
                    "Not determined. The deterministic offline engine has no rule for this "
                    f"failure class ({failure.error_type}). The observations below are real, "
                    "but no root cause has been established — set OPENAI_API_KEY to enable "
                    "AI-powered investigation."
                ),
                confidence=0.0,
                evidence=base_evidence,
                affected_files=(
                    [AffectedFile(path=failure.file, line_start=failure.line or 1,
                                  line_end=failure.line or 1, reason="named by the stack trace")]
                    if failure.file else []
                ),
                affected_endpoint=failure.endpoint,
                severity=failure.severity,
                hypotheses=[],
                failure_id=failure.id,
                reasoning_engine=ENGINE_NAME,
                grounded=True,
            ),
            None,
        )

    return (
        DiagnosisResult(
            summary=outcome.summary,
            root_cause=outcome.root_cause,
            confidence=outcome.confidence,
            evidence=_dedupe_evidence(base_evidence + outcome.evidence),
            affected_files=[
                AffectedFile(
                    path=edit.path,
                    line_start=edit.line_hint or 1,
                    line_end=edit.line_hint or 1,
                    reason=edit.reason,
                )
                for edit in outcome.edits
            ],
            affected_endpoint=failure.endpoint,
            severity=failure.severity,
            hypotheses=outcome.hypotheses,
            failure_id=failure.id,
            reasoning_engine=ENGINE_NAME,
            grounded=True,
        ),
        outcome,
    )


def _dedupe_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Collapse evidence that points at the same place.

    The baseline sweep and a matched rule both cite the raising line, which
    reads as padding in the report. The rule's detail is the more specific of
    the two, so the later item wins the slot.
    """
    ordered: list[EvidenceItem] = []
    index_by_key: dict[tuple[str, int | None], int] = {}
    for item in items:
        key = (item.source, item.line)
        existing = index_by_key.get(key)
        if existing is None:
            index_by_key[key] = len(ordered)
            ordered.append(item)
            continue
        # Keep whichever detail is more informative about the defect.
        if len(item.detail) > len(ordered[existing].detail):
            ordered[existing] = item.model_copy(
                update={"excerpt": item.excerpt or ordered[existing].excerpt}
            )
    return ordered


def _baseline_evidence(workspace: Path, failure: NormalizedFailure) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    if failure.test:
        evidence.append(
            _evidence(EvidenceKind.TEST_OUTPUT, failure.test,
                      f"this test fails with {failure.error_type}: {failure.message}"[:300])
        )
    if failure.endpoint and failure.status_code:
        evidence.append(
            _evidence(EvidenceKind.API_RESPONSE, failure.endpoint,
                      f"returned HTTP {failure.status_code}")
        )
    if failure.file and failure.line:
        source_line = _line_at(workspace, failure.file, failure.line)
        if source_line:
            evidence.append(
                _evidence(EvidenceKind.SOURCE_CODE, failure.file,
                          "the line named by the stack trace", failure.line, source_line.strip())
            )
    return evidence


def build_plan(outcome: RuleOutcome | None, failure: NormalizedFailure) -> RepairPlan:
    if outcome is None:
        return RepairPlan(
            strategy="no automated repair available in offline mode",
            steps=[],
            risk="unknown",
            expected_outcome="none",
            tests_to_run=[failure.test] if failure.test else [],
        )
    return RepairPlan(
        strategy=outcome.strategy or outcome.title,
        steps=[
            RepairPlanStep(
                order=index + 1,
                action=edit.reason or "apply the edit",
                target=f"{edit.path}:{edit.line_hint or '?'}",
                rationale=outcome.root_cause,
            )
            for index, edit in enumerate(outcome.edits)
        ],
        risk="low",
        expected_outcome=f"{failure.test or failure.endpoint or 'the failing path'} passes",
        tests_to_run=[failure.test] if failure.test else [],
    )


def build_patch(
    outcome: RuleOutcome,
    *,
    project_id: str,
    failure: NormalizedFailure,
    attempt: int,
) -> PatchProposal:
    return PatchProposal(
        id=new_patch_id(),
        project_id=project_id,
        failure_id=failure.id,
        attempt=attempt,
        title=outcome.title,
        explanation=outcome.explanation,
        edits=outcome.edits,
        tests_to_run=[failure.test] if failure.test else [],
        risk="low",
        confidence=outcome.confidence,
        reasoning_engine=ENGINE_NAME,
    )


def severity_of(failure: NormalizedFailure) -> Severity:
    return failure.severity
