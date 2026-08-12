"""OpenAI integration tests against a stubbed SDK.

There is no API key in CI, but the *shape* of what we send and how we handle what
comes back is the part most likely to break silently. These tests replace the
SDK's `responses.create` with a stub and assert:

  * the Responses API is used, with the configured model
  * a strict json_schema response format is requested
  * schema-invalid output triggers exactly one corrective retry, then stops safely
  * the tool loop dispatches to the backend registry and feeds results back as
    `function_call_output`
  * reasoning-family models are not sent a `temperature` (a hard 400)
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.agents.tools import ToolContext
from app.ai.openai_client import (
    AIError,
    OpenAIClient,
    StructuredOutputError,
)
from app.ai.schemas import AIDiagnosisResult
from app.analysis.project_analyzer import analyze_project
from app.config.settings import Settings

pytestmark = pytest.mark.asyncio


VALID_DIAGNOSIS = {
    "summary": "GET /items/1 raises KeyError.",
    "root_cause": "main.py reads the 'title' key but records store 'label'.",
    "confidence": 0.9,
    "evidence": [
        {
            "kind": "source_code",
            "source": "main.py",
            "detail": "the subscript that raises",
            "line": 16,
            "excerpt": 'item["title"]',
        }
    ],
    "affected_files": [
        {"path": "main.py", "line_start": 16, "line_end": 16, "reason": "the failing line"}
    ],
    "affected_endpoint": "GET /items/{item_id}",
    "severity": "high",
    "hypotheses": [],
}


class StubResponses:
    """Stands in for `client.responses`. Records calls, replays queued outputs."""

    def __init__(self, outputs: list[object]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.outputs:
            raise AssertionError("stub ran out of queued responses")
        nxt = self.outputs.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def text_response(payload) -> SimpleNamespace:
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        output_text=body,
        output=[],
        status="completed",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            output_tokens_details=SimpleNamespace(reasoning_tokens=10),
        ),
    )


def tool_call_response(name: str, arguments: dict, call_id: str = "call_1") -> SimpleNamespace:
    call = SimpleNamespace(
        type="function_call",
        name=name,
        call_id=call_id,
        arguments=json.dumps(arguments),
        model_dump=lambda **_: {
            "type": "function_call",
            "name": name,
            "call_id": call_id,
            "arguments": json.dumps(arguments),
        },
    )
    return SimpleNamespace(
        output_text="",
        output=[call],
        status="completed",
        usage=SimpleNamespace(
            input_tokens=80, output_tokens=20,
            output_tokens_details=SimpleNamespace(reasoning_tokens=5),
        ),
    )


def make_client(settings: Settings, outputs: list[object], model: str = "gpt-4o-mini"):
    configured = settings.model_copy(update={"openai_api_key": "sk-test-key", "openai_model": model})
    client = OpenAIClient(configured)
    stub = StubResponses(outputs)
    client._client = SimpleNamespace(responses=stub)   # noqa: SLF001 - test seam
    return client, stub


# ------------------------------------------------------- request shaping ----
async def test_uses_responses_api_with_configured_model(settings: Settings):
    client, stub = make_client(settings, [text_response(VALID_DIAGNOSIS)], model="gpt-5.1")
    result = await client.analyze_failure(instructions="inv", context="{}")

    assert isinstance(result, AIDiagnosisResult)
    assert len(stub.calls) == 1
    call = stub.calls[0]
    assert call["model"] == "gpt-5.1"
    assert call["instructions"] == "inv"
    assert call["store"] is False


def test_default_model_is_gpt_4o_mini():
    """Model selection has exactly one source, and this is its value.

    A hard-coded model at a call site would not be caught by this test, which
    is the point of asserting on the settings object every call site reads.
    """
    assert Settings().openai_model == "gpt-4o-mini"


async def test_configured_default_model_is_sent_verbatim(settings: Settings):
    """Whatever settings say is what reaches the API — no rewriting, no fallback."""
    client, stub = make_client(settings, [text_response(VALID_DIAGNOSIS)])
    await client.analyze_failure(instructions="i", context="{}")

    assert stub.calls[0]["model"] == "gpt-4o-mini"
    # gpt-4o-mini takes `temperature` and rejects `reasoning`.
    assert stub.calls[0]["temperature"] == 0.1
    assert "reasoning" not in stub.calls[0]


async def test_requests_strict_json_schema(settings: Settings):
    client, stub = make_client(settings, [text_response(VALID_DIAGNOSIS)])
    await client.analyze_failure(instructions="i", context="{}")

    fmt = stub.calls[0]["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["strict"] is True
    assert fmt["name"] == "AIDiagnosisResult"
    schema = fmt["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"].keys())


async def test_reasoning_model_gets_no_temperature(settings: Settings):
    """Reasoning-family models reject `temperature` with a 400."""
    client, stub = make_client(settings, [text_response(VALID_DIAGNOSIS)], model="gpt-5.1")
    await client.analyze_failure(instructions="i", context="{}")
    assert "temperature" not in stub.calls[0]
    assert stub.calls[0]["reasoning"] == {"effort": "medium"}


async def test_non_reasoning_model_gets_temperature(settings: Settings):
    client, stub = make_client(settings, [text_response(VALID_DIAGNOSIS)], model="gpt-4.1")
    await client.analyze_failure(instructions="i", context="{}")
    assert stub.calls[0]["temperature"] == 0.1
    assert "reasoning" not in stub.calls[0]


# ---------------------------------------------------- output validation ----
async def test_invalid_output_triggers_one_corrective_retry(settings: Settings):
    """The validation errors are fed back so the model can correct itself."""
    broken = {**VALID_DIAGNOSIS}
    broken.pop("root_cause")
    client, stub = make_client(
        settings, [text_response(broken), text_response(VALID_DIAGNOSIS)]
    )

    result = await client.analyze_failure(instructions="i", context="{}")
    assert result.root_cause.startswith("main.py reads")
    assert len(stub.calls) == 2

    followup = stub.calls[1]["input"]
    correction = followup[-1]["content"]
    assert "did not satisfy the required schema" in correction
    assert "root_cause" in correction, "the specific validation error must be fed back"
    assert client.calls[0].retried is True


async def test_twice_invalid_stops_safely(settings: Settings):
    """Never act on malformed model output — stop instead."""
    broken = text_response({"summary": "x"})
    client, stub = make_client(settings, [broken, broken])

    with pytest.raises(StructuredOutputError) as excinfo:
        await client.analyze_failure(instructions="i", context="{}")

    assert "stopping" in str(excinfo.value)
    assert excinfo.value.errors
    assert len(stub.calls) == 2, "exactly one retry, not an unbounded loop"


async def test_non_json_output_stops_safely(settings: Settings):
    prose = text_response("I think the bug is in main.py, but here is no JSON.")
    client, _stub = make_client(settings, [prose, prose])
    with pytest.raises(StructuredOutputError):
        await client.analyze_failure(instructions="i", context="{}")


async def test_truncated_response_is_retried_shorter(settings: Settings):
    truncated = text_response(VALID_DIAGNOSIS)
    truncated.status = "incomplete"
    truncated.incomplete_details = SimpleNamespace(reason="max_output_tokens")
    client, stub = make_client(settings, [truncated, text_response(VALID_DIAGNOSIS)])

    await client.analyze_failure(instructions="i", context="{}")
    assert len(stub.calls) == 2
    assert "incomplete" in stub.calls[1]["input"][-1]["content"]


async def test_api_error_surfaces_as_ai_error(settings: Settings):
    client, _stub = make_client(settings, [RuntimeError("connection reset")])
    with pytest.raises(AIError, match="connection reset"):
        await client.analyze_failure(instructions="i", context="{}")


async def test_usage_is_accounted(settings: Settings):
    client, _stub = make_client(settings, [text_response(VALID_DIAGNOSIS)])
    await client.analyze_failure(instructions="i", context="{}")
    usage = client.usage_summary()
    assert usage["calls"] == 1
    assert usage["input_tokens"] == 100
    assert usage["reasoning_tokens"] == 10


# ------------------------------------------------------------ tool loop ----
async def test_tool_loop_dispatches_and_feeds_results_back(
    settings: Settings, sample_project
):
    metadata = analyze_project(sample_project)
    from app.execution.local_runner import LocalRunner

    ctx = ToolContext(
        workspace=sample_project,
        metadata=metadata,
        settings=settings,
        sandbox=LocalRunner(settings),
    )

    client, stub = make_client(
        settings,
        [
            tool_call_response("read_file", {"path": "main.py"}),
            text_response(VALID_DIAGNOSIS),   # no more tool calls -> loop exits
            text_response(VALID_DIAGNOSIS),   # final structured conclusion
        ],
    )

    seen: list[tuple[str, dict]] = []

    async def executor(name: str, args: dict) -> dict:
        seen.append((name, args))
        from app.agents.tools import execute_tool

        return await execute_tool(ctx, name, args)

    result = await client.run_tool_loop(
        stage="investigate",
        instructions="investigate",
        user_input="{}",
        tools=[{"type": "function", "name": "read_file", "description": "", "parameters": {}}],
        tool_executor=executor,
        final_schema=AIDiagnosisResult,
    )

    assert seen == [("read_file", {"path": "main.py"})]
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].ok

    # The tool output must be returned to the model as a function_call_output.
    second_call_input = stub.calls[1]["input"]
    outputs = [item for item in second_call_input if item.get("type") == "function_call_output"]
    assert len(outputs) == 1
    assert outputs[0]["call_id"] == "call_1"
    assert "FastAPI" in outputs[0]["output"]

    assert isinstance(result.payload, AIDiagnosisResult)


async def test_tool_loop_survives_a_failing_tool(settings: Settings, sample_project):
    metadata = analyze_project(sample_project)
    from app.execution.local_runner import LocalRunner

    ctx = ToolContext(
        workspace=sample_project, metadata=metadata, settings=settings,
        sandbox=LocalRunner(settings),
    )
    client, stub = make_client(
        settings,
        [
            tool_call_response("read_file", {"path": "../../../etc/passwd"}),
            text_response(VALID_DIAGNOSIS),
            text_response(VALID_DIAGNOSIS),
        ],
    )

    async def executor(name: str, args: dict) -> dict:
        from app.agents.tools import execute_tool

        return await execute_tool(ctx, name, args)

    result = await client.run_tool_loop(
        stage="investigate", instructions="i", user_input="{}",
        tools=[], tool_executor=executor, final_schema=AIDiagnosisResult,
    )

    assert result.tool_calls[0].ok is False
    assert "error" in result.tool_calls[0].output
    # The failure is reported back to the model rather than killing the run.
    outputs = [
        item for item in stub.calls[1]["input"] if item.get("type") == "function_call_output"
    ]
    assert "not allowed" in outputs[0]["output"] or "escape" in outputs[0]["output"]


async def test_tool_loop_respects_the_iteration_ceiling(settings: Settings, sample_project):
    """A model that never stops calling tools must still terminate."""
    metadata = analyze_project(sample_project)
    from app.execution.local_runner import LocalRunner

    ctx = ToolContext(
        workspace=sample_project, metadata=metadata, settings=settings,
        sandbox=LocalRunner(settings),
    )
    limit = 3
    outputs: list[object] = [
        tool_call_response("read_file", {"path": "main.py"}, call_id=f"call_{i}")
        for i in range(limit)
    ]
    outputs.append(text_response(VALID_DIAGNOSIS))   # the forced conclusion
    client, _stub = make_client(settings, outputs)

    async def executor(name: str, args: dict) -> dict:
        from app.agents.tools import execute_tool

        return await execute_tool(ctx, name, args)

    result = await client.run_tool_loop(
        stage="investigate", instructions="i", user_input="{}",
        tools=[], tool_executor=executor, final_schema=AIDiagnosisResult,
        max_iterations=limit,
    )

    assert result.iterations == limit
    assert result.stopped_reason == "iteration_limit"
    assert isinstance(result.payload, AIDiagnosisResult)
