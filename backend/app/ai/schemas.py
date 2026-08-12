"""Structured-output schemas for the OpenAI Responses API.

The model never returns free text that the system acts on. Every stage requests
a `json_schema` response format with `strict: true`, and the payload is then
validated a second time against a Pydantic model here before anything touches
the workspace. Two layers, because "the API said it was valid JSON" and "this is
a patch I am willing to apply" are different claims.

OpenAI strict mode requires, for every object: `additionalProperties: false` and
every property listed in `required`. `strict_schema()` enforces that mechanically
so a hand-written schema cannot drift out of spec.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Response payloads the model is asked to produce
# ---------------------------------------------------------------------------


class AIEvidenceItem(BaseModel):
    kind: Literal[
        "stack_trace", "source_code", "test_output", "test_code",
        "api_response", "api_contract", "project_metadata", "log",
    ] = Field(description="What kind of artefact this evidence comes from.")
    source: str = Field(
        description="The exact artefact this came from: a file path, a pytest node id, or an endpoint. Must exist in the project."
    )
    detail: str = Field(description="What this artefact shows. One sentence. State only what is literally observable.")
    line: int = Field(description="Line number in the source file, or 0 if not line-specific.")
    excerpt: str = Field(description="A short verbatim excerpt copied from the artefact, or an empty string.")


class AIAffectedFile(BaseModel):
    path: str = Field(description="Project-relative path, e.g. 'main.py' or 'app/routes/users.py'.")
    line_start: int = Field(description="First affected line (1-indexed).")
    line_end: int = Field(description="Last affected line (1-indexed).")
    reason: str = Field(description="Why this file is implicated.")


class AIHypothesis(BaseModel):
    statement: str = Field(description="A candidate explanation, phrased as a hypothesis.")
    confidence: float = Field(description="0.0 to 1.0.")
    supporting_evidence: list[str] = Field(description="Evidence sources that support it.")
    status: Literal["open", "supported", "rejected"] = Field(description="Whether the evidence gathered supports it.")


class AIDiagnosisResult(BaseModel):
    """Root-cause conclusion. Every claim must be traceable to evidence."""

    summary: str = Field(description="One or two sentences describing the failure as observed.")
    root_cause: str = Field(description="The specific defect in the code that causes the failure. Not a symptom.")
    confidence: float = Field(description="0.0 to 1.0. Be honest; low confidence is acceptable.")
    evidence: list[AIEvidenceItem] = Field(description="Concrete observations. Never invent a file, line or message.")
    affected_files: list[AIAffectedFile] = Field(description="Files that must change to fix the root cause.")
    affected_endpoint: str = Field(description="e.g. 'GET /users/{user_id}', or an empty string if not endpoint-specific.")
    severity: Literal["critical", "high", "medium", "low"]
    hypotheses: list[AIHypothesis] = Field(description="Alternatives considered, including rejected ones.")


class AIRepairPlanStep(BaseModel):
    order: int
    action: str = Field(description="What to change, concretely.")
    target: str = Field(description="File and symbol this step touches.")
    rationale: str = Field(description="Why this step is necessary to address the root cause.")


class AIRepairPlan(BaseModel):
    strategy: str = Field(description="The minimal change that addresses the root cause.")
    steps: list[AIRepairPlanStep]
    risk: Literal["low", "medium", "high"]
    expected_outcome: str = Field(description="What should be observably different after the fix.")
    tests_to_run: list[str] = Field(description="pytest node ids to run first, most specific first.")


class AIFileEdit(BaseModel):
    path: str = Field(description="Project-relative path of the file to change.")
    operation: Literal["replace", "insert_after", "create_file"]
    old: str = Field(
        description=(
            "For replace/insert_after: text copied VERBATIM from the current file, "
            "including indentation. It must appear EXACTLY ONCE in that file. "
            "Include surrounding lines if needed to make it unique. Empty for create_file."
        )
    )
    new: str = Field(description="The replacement text (or the file body for create_file).")
    line_hint: int = Field(description="Approximate line number of the change, or 0.")
    reason: str = Field(description="Why this specific edit is required.")


class AIPatchProposal(BaseModel):
    title: str = Field(description="Short imperative summary, e.g. \"Use the 'name' key instead of 'username'\".")
    explanation: str = Field(description="Why this fixes the root cause, referencing the evidence.")
    edits: list[AIFileEdit] = Field(description="The smallest set of edits that fixes the root cause.")
    tests_to_run: list[str] = Field(description="pytest node ids that should now pass.")
    risk: Literal["low", "medium", "high"]
    confidence: float = Field(description="0.0 to 1.0.")


class AIPatchReview(BaseModel):
    """A second look at a generated patch before it is shown to the developer."""

    approve: bool = Field(description="False if the patch is wrong, unsafe, or larger than necessary.")
    concerns: list[str] = Field(description="Specific problems found. Empty if none.")
    addresses_root_cause: bool
    is_minimal: bool
    introduces_risk: bool
    revised_explanation: str = Field(description="A clearer explanation for the developer, or an empty string.")


class AIVerificationAnalysis(BaseModel):
    """Interpretation of a post-patch test run.

    Advisory only: the authoritative pass/fail comes from the pytest exit code.
    """

    original_failure_resolved: bool = Field(description="Did the specific failure under repair stop occurring?")
    regressions_introduced: bool = Field(description="Did any test that previously passed start failing?")
    remaining_failures: list[str] = Field(description="Node ids or endpoints still failing.")
    verdict_reason: str = Field(description="One sentence explaining the outcome, citing the test output.")
    next_action: Literal["stop", "retry", "rollback"]
    retry_guidance: str = Field(description="If retrying: what was wrong with the previous attempt and what to try instead.")
    confidence: float


class AIFailedRepairAnalysis(BaseModel):
    """Post-mortem of a failed attempt, used to steer the next one."""

    why_it_failed: str = Field(description="Why the previous patch did not fix the failure.")
    was_diagnosis_wrong: bool = Field(description="True if the root cause itself was misidentified.")
    revised_root_cause: str = Field(description="Corrected root cause, or an empty string if unchanged.")
    what_to_investigate: list[str] = Field(description="Specific files, symbols or tests to look at next.")
    different_approach: str = Field(description="A materially different fix strategy to try.")
    should_retry: bool = Field(description="False if further attempts are unlikely to help.")


class AIToolRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AIAgentDecision(BaseModel):
    """One turn of the investigation loop when the model drives it explicitly."""

    reasoning: str = Field(description="What you now know and what you still need.")
    action: Literal["investigate", "conclude"] = Field(
        description="'investigate' to request more context, 'conclude' when the root cause is established."
    )
    tool: str = Field(description="Tool name when action is 'investigate', otherwise an empty string.")
    arguments_json: str = Field(
        description="JSON object of arguments for the tool, as a string. '{}' when concluding."
    )
    confidence: float = Field(description="Current confidence in the root cause, 0.0 to 1.0.")


# ---------------------------------------------------------------------------
# JSON-schema generation for `text.format`
# ---------------------------------------------------------------------------

_STRIP_KEYS = {"title", "default", "examples", "$comment", "discriminator"}


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic model -> an OpenAI strict-mode-compatible JSON schema."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})
    resolved = _inline_refs(schema, definitions)
    return _harden(resolved)


def _inline_refs(node: Any, definitions: dict, depth: int = 0) -> Any:
    """Strict mode disallows `$ref` chains we cannot control, so inline them."""
    if depth > 24:
        return node
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"]
            name = ref.rsplit("/", 1)[-1]
            target = definitions.get(name)
            if target is None:
                return {"type": "string"}
            merged = _inline_refs(dict(target), definitions, depth + 1)
            extras = {k: v for k, v in node.items() if k != "$ref"}
            merged.update(_inline_refs(extras, definitions, depth + 1))
            return merged
        return {key: _inline_refs(value, definitions, depth + 1) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline_refs(item, definitions, depth + 1) for item in node]
    return node


def _harden(node: Any) -> Any:
    """Apply the strict-mode invariants recursively."""
    if isinstance(node, list):
        return [_harden(item) for item in node]
    if not isinstance(node, dict):
        return node

    cleaned = {key: _harden(value) for key, value in node.items() if key not in _STRIP_KEYS}

    if cleaned.get("type") == "object" or "properties" in cleaned:
        cleaned["type"] = "object"
        properties = cleaned.get("properties") or {}
        cleaned["properties"] = properties
        # Strict mode: every declared property must be required.
        cleaned["required"] = list(properties.keys())
        cleaned["additionalProperties"] = False
    if cleaned.get("type") == "array" and "items" not in cleaned:
        cleaned["items"] = {"type": "string"}
    # `anyOf` with null (Optional[...]) is legal; nothing to do.
    return cleaned


def text_format_for(model: type[BaseModel], name: str | None = None) -> dict:
    """Build the `text` argument for `responses.create`."""
    return {
        "format": {
            "type": "json_schema",
            "name": name or model.__name__,
            "schema": strict_schema(model),
            "strict": True,
        }
    }
