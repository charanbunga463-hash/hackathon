"""Deterministic engine tests.

The offline engine is the fallback reasoning path. It must be *conservative*:
when no rule matches it has to say so rather than guess, and the evidence it
produces has to be as well-formed as the AI path's, because both feed the same
grounding check and the same report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.offline_engine import (
    ENGINE_NAME,
    _dict_keys_in_file,
    _looks_like_dict_key,
    build_patch,
    diagnose,
)
from app.analysis.project_analyzer import analyze_project
from app.config.settings import Settings
from app.models.execution import NormalizedFailure, Severity, StackFrame
from app.patches.patch_validator import validate_patch


def _failure(**overrides) -> NormalizedFailure:
    base = dict(
        id="fail_1",
        error_type="KeyError",
        message="'username'",
        file="main.py",
        line=42,
        test="tests/test_users.py::test_get_user",
        severity=Severity.HIGH,
        frames=[StackFrame(file="main.py", line=42, function="get_user", in_project=True)],
    )
    base.update(overrides)
    return NormalizedFailure(**base)


@pytest.fixture
def keyerror_demo(demo_workspace):
    workspace = demo_workspace("fastapi-keyerror")
    return workspace, analyze_project(workspace)


# ------------------------------------------------------------ dict keys ----
@pytest.mark.parametrize(
    "value,expected",
    [
        ("name", True),
        ("user_id", True),
        ("/health", False),
        ("/users/{user_id}", False),
        ("", False),
        ("has space", False),
        ("with-dash", False),
    ],
)
def test_looks_like_dict_key(value, expected):
    assert _looks_like_dict_key(value) is expected


def test_dict_keys_ignores_route_decorators(keyerror_demo):
    """`@app.get("/health")` parses like `record.get("health")` — it must not
    be collected as a dictionary key."""
    workspace, _metadata = keyerror_demo
    keys = _dict_keys_in_file(workspace, "main.py")
    assert "name" in keys
    assert "email" in keys
    assert not any(key.startswith("/") for key in keys), keys
    assert "health" not in keys


# ------------------------------------------------------------- evidence ----
def test_evidence_source_has_no_doubled_line_suffix(keyerror_demo):
    """`source` is the file; the line lives in its own field.

    Emitting "main.py:42" as the source alongside line=42 renders as
    "main.py:42:42" in the report.
    """
    workspace, metadata = keyerror_demo
    result, outcome = diagnose(workspace, metadata, _failure())
    assert outcome is not None
    for item in result.evidence:
        assert not item.source.rstrip("0123456789").endswith(":"), item.source
        if item.line:
            assert ":" not in item.source or item.source.count(":") == item.source.count("::")


def test_evidence_is_grounded_in_real_files(keyerror_demo):
    workspace, metadata = keyerror_demo
    result, _outcome = diagnose(workspace, metadata, _failure())
    assert result.evidence
    for item in result.evidence:
        assert item.verified
        candidate = item.source.split("::")[0]
        if candidate.endswith(".py"):
            assert (workspace / candidate).exists(), item.source


def test_evidence_is_deduplicated(keyerror_demo):
    """The baseline sweep and a matched rule both cite the raising line."""
    workspace, metadata = keyerror_demo
    result, _outcome = diagnose(workspace, metadata, _failure())
    keys = [(item.source, item.line) for item in result.evidence]
    assert len(keys) == len(set(keys)), keys


def test_diagnosis_is_labelled_as_not_ai(keyerror_demo):
    workspace, metadata = keyerror_demo
    result, _outcome = diagnose(workspace, metadata, _failure())
    assert result.reasoning_engine == ENGINE_NAME
    assert result.reasoning_engine != "openai"


# ---------------------------------------------------------------- rules ----
def test_key_error_rule_targets_the_subscript_not_the_response_key(
    keyerror_demo, settings: Settings
):
    """`"username": user["username"]` — only the lookup may change.

    Rewriting the response key instead would silently change the API contract
    while making the test pass for the wrong reason.
    """
    workspace, metadata = keyerror_demo
    failure = _failure()
    result, outcome = diagnose(workspace, metadata, failure)
    assert outcome is not None

    patch = build_patch(outcome, project_id="prj", failure=failure, attempt=1)
    validation = validate_patch(workspace, patch, settings)
    assert validation.valid, [i.message for i in validation.issues]

    edit = patch.edits[0]
    assert 'user["name"]' in edit.new
    assert '"username":' in edit.new, "the response key must be preserved"
    assert result.confidence >= 0.7


def test_unknown_failure_class_yields_no_patch_and_zero_confidence(keyerror_demo):
    """The engine must refuse to guess rather than invent a root cause."""
    workspace, metadata = keyerror_demo
    failure = _failure(
        error_type="SomeExoticDomainError",
        message="the quarterly forecast is inconsistent",
    )
    result, outcome = diagnose(workspace, metadata, failure)
    assert outcome is None
    assert result.confidence == 0.0
    assert "not determined" in result.root_cause.lower()
    assert result.grounded
    # It still reports what it actually observed.
    assert result.evidence


def test_key_error_with_no_similar_key_declines(demo_workspace):
    workspace = demo_workspace("fastapi-keyerror")
    metadata = analyze_project(workspace)
    failure = _failure(message="'zzzzzzzzzzzz'")
    _result, outcome = diagnose(workspace, metadata, failure)
    assert outcome is None, "no plausible replacement key exists, so no patch may be proposed"


@pytest.mark.parametrize(
    "slug,error_type",
    [
        ("fastapi-attribute-error", "AttributeError"),
        ("fastapi-billing", "ZeroDivisionError"),
        ("fastapi-type-error", "TypeError"),
    ],
)
def test_rules_produce_applicable_patches(slug, error_type, demo_workspace, settings: Settings):
    """Each rule's patch must validate against the real file, not just parse."""
    import asyncio

    from app.execution.sandbox import build_sandbox
    from app.execution.test_runner import run_tests

    workspace = demo_workspace(slug)
    metadata = analyze_project(workspace)
    sandbox = asyncio.run(build_sandbox(settings))
    run = asyncio.run(run_tests(sandbox, workspace))
    assert run.failures, f"{slug} should start broken"

    failure = run.failures[0]
    assert failure.error_type == error_type
    _result, outcome = diagnose(workspace, metadata, failure)
    assert outcome is not None, f"no rule matched {error_type}"

    patch = build_patch(outcome, project_id="prj", failure=failure, attempt=1)
    validation = validate_patch(workspace, patch, settings)
    assert validation.valid, [i.message for i in validation.issues]
    assert validation.lines_added + validation.lines_removed <= 8, "the fix should be minimal"
