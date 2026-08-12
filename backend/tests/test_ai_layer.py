"""AI layer tests.

These run without an API key: they cover the schema contract, the context
builder, and the grounding check that stops fabricated evidence reaching the UI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents import diagnostician
from app.agents.tools import TOOL_SCHEMAS, investigation_tool_schemas
from app.ai.context_builder import build_failure_context, summarize_failure
from app.ai.openai_client import AINotConfiguredError, OpenAIClient
from app.ai.schemas import (
    AIDiagnosisResult,
    AIEvidenceItem,
    AIPatchProposal,
    AIVerificationAnalysis,
    strict_schema,
    text_format_for,
)
from app.analysis.project_analyzer import analyze_project
from app.config.settings import Settings
from app.models.execution import NormalizedFailure, Severity


def _walk_objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from _walk_objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_objects(item)


@pytest.mark.parametrize(
    "model", [AIDiagnosisResult, AIPatchProposal, AIVerificationAnalysis, AIEvidenceItem]
)
def test_strict_schema_satisfies_openai_rules(model):
    """OpenAI strict mode: every object needs all properties required + no extras."""
    schema = strict_schema(model)
    objects = list(_walk_objects(schema))
    assert objects, "schema should contain at least one object"
    for obj in objects:
        assert obj.get("additionalProperties") is False
        assert set(obj.get("required", [])) == set(obj.get("properties", {}).keys())


def test_strict_schema_has_no_refs():
    """`$ref` chains are inlined so the schema is self-contained."""
    import json

    text = json.dumps(strict_schema(AIDiagnosisResult))
    assert "$ref" not in text
    assert "$defs" not in text


def test_text_format_shape():
    payload = text_format_for(AIDiagnosisResult)
    assert payload["format"]["type"] == "json_schema"
    assert payload["format"]["strict"] is True
    assert payload["format"]["name"] == "AIDiagnosisResult"


def test_tool_schemas_are_well_formed():
    for schema in TOOL_SCHEMAS:
        assert schema["type"] == "function"
        assert schema["name"]
        params = schema["parameters"]
        assert params["additionalProperties"] is False
        assert set(params["required"]) == set(params["properties"].keys())


def test_no_shell_tool_is_exposed():
    """The model must never be able to request arbitrary command execution."""
    names = {schema["name"] for schema in TOOL_SCHEMAS}
    for forbidden in ("run_shell", "shell", "exec", "bash", "run_command", "system"):
        assert forbidden not in names


def test_mutating_tools_are_not_exposed_to_the_model():
    names = {schema["name"] for schema in TOOL_SCHEMAS}
    assert "apply_patch" not in names
    assert "rollback_patch" not in names
    assert "validate_patch" in names   # dry-run only


def test_investigation_schemas_can_exclude_execution():
    names = {s["name"] for s in investigation_tool_schemas(allow_execution=False)}
    assert "run_full_tests" not in names
    assert "read_file" in names


@pytest.mark.asyncio
async def test_client_raises_without_key(settings: Settings):
    client = OpenAIClient(settings)
    assert not client.configured
    with pytest.raises(AINotConfiguredError):
        await client.analyze_failure(instructions="x", context="y")


@pytest.mark.asyncio
async def test_connectivity_reports_missing_key(settings: Settings):
    result = await OpenAIClient(settings).check_connectivity()
    assert result["ok"] is False
    assert result["configured"] is False


def test_public_system_info_never_leaks_the_key():
    settings = Settings(openai_api_key="sk-super-secret-value-1234567890")
    info = settings.public_system_info()
    serialized = str(info)
    assert "sk-super-secret-value-1234567890" not in serialized
    assert info["openai_configured"] is True
    assert info["openai_key_hint"] == "sk-...7890"


# ------------------------------------------------------------- grounding ---
def _failure() -> NormalizedFailure:
    return NormalizedFailure(
        id="fail_1", error_type="KeyError", message="'username'",
        file="main.py", line=15, test="tests/test_items.py::test_get_item",
        severity=Severity.HIGH,
    )


def _ai_diagnosis(sources: list[tuple[str, int]]) -> AIDiagnosisResult:
    return AIDiagnosisResult(
        summary="s", root_cause="rc", confidence=0.95,
        evidence=[
            AIEvidenceItem(kind="source_code", source=source, detail="d", line=line, excerpt="")
            for source, line in sources
        ],
        affected_files=[], affected_endpoint="", severity="high", hypotheses=[],
    )


def test_grounding_keeps_real_sources(sample_project: Path):
    metadata = analyze_project(sample_project)
    result = diagnostician.from_ai(
        sample_project, metadata, _failure(), _ai_diagnosis([("main.py", 5)])
    )
    assert result.grounded
    assert result.evidence[0].verified
    assert result.confidence == pytest.approx(0.95)


def test_grounding_drops_hallucinated_file(sample_project: Path):
    metadata = analyze_project(sample_project)
    result = diagnostician.from_ai(
        sample_project, metadata,
        _failure(),
        _ai_diagnosis([("app/services/does_not_exist.py", 212)]),
    )
    assert not result.grounded
    assert result.evidence == []
    assert result.ungrounded_evidence
    # A diagnosis whose evidence evaporated cannot keep 0.95 confidence.
    assert result.confidence <= 0.3


def test_grounding_drops_impossible_line_number(sample_project: Path):
    metadata = analyze_project(sample_project)
    result = diagnostician.from_ai(
        sample_project, metadata, _failure(), _ai_diagnosis([("main.py", 99999)])
    )
    assert not result.grounded
    assert "does not exist" in result.ungrounded_evidence[0]


def test_grounding_accepts_known_endpoint(sample_project: Path):
    metadata = analyze_project(sample_project)
    result = diagnostician.from_ai(
        sample_project, metadata, _failure(), _ai_diagnosis([("GET /items/{item_id}", 0)])
    )
    assert result.grounded


def test_grounding_rejects_unknown_endpoint(sample_project: Path):
    metadata = analyze_project(sample_project)
    result = diagnostician.from_ai(
        sample_project, metadata, _failure(), _ai_diagnosis([("GET /nope/{id}", 0)])
    )
    assert not result.grounded


# --------------------------------------------------------- context builder --
def test_build_failure_context_includes_real_source(sample_project: Path):
    metadata = analyze_project(sample_project)
    context = build_failure_context(sample_project, metadata, _failure())
    assert context["failure"]["error_type"] == "KeyError"
    assert context["candidate_files"]
    paths = {entry["path"] for entry in context["candidate_files"]}
    assert "main.py" in paths
    main_entry = next(e for e in context["candidate_files"] if e["path"] == "main.py")
    assert main_entry["found"]
    assert "app = FastAPI()" in main_entry["content"]


def test_summarize_failure_truncates_traceback():
    failure = _failure().model_copy(update={"traceback": "x" * 50_000})
    assert len(summarize_failure(failure)["traceback"]) <= 6000
