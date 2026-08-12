"""The single place in this codebase that talks to OpenAI.

Nothing else imports the `openai` package. Every stage of the agent calls a
named method here, so the provider, the model, retry policy, structured-output
handling and token accounting all live in one auditable file.

Design notes:

* Uses the **Responses API** (`client.responses.create`).
* Every call requests a strict `json_schema` response format and the payload is
  validated against a Pydantic model. Invalid output triggers ONE corrective
  retry that feeds the validation error back to the model; a second failure
  raises `StructuredOutputError` and the caller stops safely. Malformed model
  output is never executed or applied.
* The model can request *tools*, but only from a fixed registry implemented by
  the backend. It cannot ask for a shell command — there is no tool that runs one.
* `OPENAI_API_KEY` is read from settings, never logged, never returned by any
  API route, and never written into a generated project file.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from ..config.settings import Settings
from ..utils.logging import get_logger
from ..utils.timestamps import elapsed_ms, monotonic_ms
from .schemas import (
    AIDiagnosisResult,
    AIFailedRepairAnalysis,
    AIPatchProposal,
    AIPatchReview,
    AIRepairPlan,
    AIVerificationAnalysis,
    text_format_for,
)

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class AIError(RuntimeError):
    """Base class for AI-layer failures."""


class AINotConfiguredError(AIError):
    """Raised when no API key is configured and an OpenAI call is attempted."""


class StructuredOutputError(AIError):
    """Model output failed schema validation twice. The caller must stop safely."""

    def __init__(self, message: str, raw: str = "", errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.raw = raw
        self.errors = errors or []


@dataclass
class AICallRecord:
    """Bookkeeping for one model call, surfaced in the investigation report."""

    stage: str
    model: str
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    retried: bool = False
    tool_calls: int = 0
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "stage": self.stage,
            "model": self.model,
            "duration_ms": self.duration_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "retried": self.retried,
            "tool_calls": self.tool_calls,
            "error": self.error,
        }


@dataclass
class ToolCallOutcome:
    call_id: str
    name: str
    arguments: dict
    output: dict
    ok: bool = True
    duration_ms: int = 0


@dataclass
class AgentLoopResult:
    """Outcome of a tool-using investigation loop."""

    payload: BaseModel | None
    tool_calls: list[ToolCallOutcome] = field(default_factory=list)
    iterations: int = 0
    records: list[AICallRecord] = field(default_factory=list)
    stopped_reason: str = "completed"


# Reasoning-family models reject `temperature`; sending it is a hard 400.
_NO_TEMPERATURE_PREFIXES = ("gpt-5", "o1", "o3", "o4", "gpt-6")
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4", "gpt-6")


class OpenAIClient:
    """Typed, schema-validated access to the configured OpenAI model."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.openai_model
        self._client = None
        self.calls: list[AICallRecord] = []

    # ------------------------------------------------------------ plumbing --
    @property
    def configured(self) -> bool:
        return bool(self.settings.openai_api_key)

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self.configured:
            raise AINotConfiguredError(
                "OPENAI_API_KEY is not set. Set it in the environment (never in a project "
                "file) to enable AI-powered diagnosis."
            )
        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {
            "api_key": self.settings.openai_api_key,
            "timeout": self.settings.openai_timeout_seconds,
            "max_retries": self.settings.openai_max_retries,
        }
        if self.settings.openai_base_url:
            kwargs["base_url"] = self.settings.openai_base_url
        self._client = AsyncOpenAI(**kwargs)
        return self._client

    def _supports_temperature(self) -> bool:
        return not self.model.lower().startswith(_NO_TEMPERATURE_PREFIXES)

    def _supports_reasoning(self) -> bool:
        return self.model.lower().startswith(_REASONING_PREFIXES)

    def _base_kwargs(self) -> dict:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_output_tokens": self.settings.openai_max_output_tokens,
            "store": False,
        }
        if self._supports_temperature():
            kwargs["temperature"] = 0.1
        if self._supports_reasoning():
            kwargs["reasoning"] = {"effort": self.settings.openai_reasoning_effort}
        return kwargs

    @staticmethod
    def _output_text(response) -> str:
        text = getattr(response, "output_text", None)
        if text:
            return text
        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                value = getattr(content, "text", None)
                if value:
                    chunks.append(value)
        return "".join(chunks)

    @staticmethod
    def _usage(response) -> tuple[int, int, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0, 0
        details = getattr(usage, "output_tokens_details", None)
        reasoning = getattr(details, "reasoning_tokens", 0) if details else 0
        return (
            getattr(usage, "input_tokens", 0) or 0,
            getattr(usage, "output_tokens", 0) or 0,
            reasoning or 0,
        )

    def _record(self, record: AICallRecord) -> AICallRecord:
        self.calls.append(record)
        return record

    # ------------------------------------------------- structured requests --
    async def _structured(
        self,
        *,
        stage: str,
        instructions: str,
        user_input: str,
        schema: type[T],
        schema_name: str | None = None,
    ) -> T:
        """One structured call with a single corrective retry on invalid output."""
        client = self._ensure_client()
        started = monotonic_ms()
        record = self._record(AICallRecord(stage=stage, model=self.model))

        conversation: list[dict] = [{"role": "user", "content": user_input}]
        last_error: str = ""
        raw = ""

        for attempt in (1, 2):
            try:
                response = await client.responses.create(
                    **self._base_kwargs(),
                    instructions=instructions,
                    input=conversation,
                    text=text_format_for(schema, schema_name),
                )
            except Exception as exc:  # noqa: BLE001 - surfaced to the operator
                record.error = f"{type(exc).__name__}: {exc}"
                record.duration_ms = elapsed_ms(started)
                raise AIError(f"OpenAI request failed during {stage}: {exc}") from exc

            raw = self._output_text(response)
            tokens_in, tokens_out, reasoning = self._usage(response)
            record.input_tokens += tokens_in
            record.output_tokens += tokens_out
            record.reasoning_tokens += reasoning

            if getattr(response, "status", None) == "incomplete":
                reason = getattr(getattr(response, "incomplete_details", None), "reason", "unknown")
                last_error = f"the response was truncated ({reason}); return a shorter payload"
                if attempt == 1:
                    record.retried = True
                    conversation += [
                        {"role": "assistant", "content": raw or "(truncated)"},
                        {"role": "user", "content": f"Your previous response was incomplete: {reason}. "
                                                    "Return the same JSON but much more concise."},
                    ]
                    continue

            try:
                parsed = schema.model_validate_json(raw)
                record.duration_ms = elapsed_ms(started)
                return parsed
            except ValidationError as exc:
                last_error = _format_validation_error(exc)
                logger.warning("%s: structured output failed validation (attempt %d): %s",
                               stage, attempt, last_error[:400])
                if attempt == 1:
                    record.retried = True
                    conversation += [
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": (
                                "Your previous response did not satisfy the required schema.\n"
                                f"Validation errors:\n{last_error}\n\n"
                                "Return corrected JSON that matches the schema exactly. "
                                "Do not add commentary."
                            ),
                        },
                    ]
                    continue

        record.error = last_error
        record.duration_ms = elapsed_ms(started)
        raise StructuredOutputError(
            f"{stage}: the model returned data that failed schema validation twice; "
            "stopping instead of acting on malformed output.",
            raw=raw,
            errors=[last_error],
        )

    # ------------------------------------------------------ the tool loop --
    async def run_tool_loop(
        self,
        *,
        stage: str,
        instructions: str,
        user_input: str,
        tools: list[dict],
        tool_executor: Callable[[str, dict], Awaitable[dict]],
        final_schema: type[T],
        max_iterations: int | None = None,
        on_tool_call: Callable[[str, dict], Awaitable[None]] | None = None,
        on_tool_result: Callable[[str, dict, dict], Awaitable[None]] | None = None,
    ) -> AgentLoopResult:
        """Let the model gather evidence with controlled tools, then conclude.

        The model chooses *which* tool to call; the backend decides what that
        tool actually does. There is no tool that executes a model-authored
        command. When the model stops calling tools, one final structured call
        produces the schema-validated conclusion.
        """
        client = self._ensure_client()
        limit = max_iterations or self.settings.agent_max_tool_iterations
        conversation: list[dict] = [{"role": "user", "content": user_input}]
        outcomes: list[ToolCallOutcome] = []
        records: list[AICallRecord] = []
        iterations = 0
        stopped_reason = "completed"

        while iterations < limit:
            iterations += 1
            started = monotonic_ms()
            record = AICallRecord(stage=f"{stage}.iter{iterations}", model=self.model)
            records.append(record)
            self.calls.append(record)
            try:
                response = await client.responses.create(
                    **self._base_kwargs(),
                    instructions=instructions,
                    input=conversation,
                    tools=tools,
                    tool_choice="auto",
                    parallel_tool_calls=False,
                )
            except Exception as exc:  # noqa: BLE001
                record.error = f"{type(exc).__name__}: {exc}"
                record.duration_ms = elapsed_ms(started)
                raise AIError(f"OpenAI request failed during {stage}: {exc}") from exc

            tokens_in, tokens_out, reasoning = self._usage(response)
            record.input_tokens, record.output_tokens, record.reasoning_tokens = (
                tokens_in, tokens_out, reasoning
            )
            record.duration_ms = elapsed_ms(started)

            output_items = list(getattr(response, "output", []) or [])
            function_calls = [
                item for item in output_items
                if getattr(item, "type", "") == "function_call"
            ]

            # Carry the model's own output forward so it keeps its reasoning state.
            for item in output_items:
                conversation.append(_serialize_output_item(item))

            if not function_calls:
                break

            record.tool_calls = len(function_calls)
            allowed = self.settings.agent_max_tool_calls_per_iteration
            for call in function_calls[:allowed]:
                name = getattr(call, "name", "")
                call_id = getattr(call, "call_id", "") or getattr(call, "id", "")
                try:
                    arguments = json.loads(getattr(call, "arguments", "") or "{}")
                    if not isinstance(arguments, dict):
                        arguments = {"value": arguments}
                except json.JSONDecodeError as exc:
                    arguments = {}
                    logger.warning("tool %s had malformed arguments: %s", name, exc)

                if on_tool_call is not None:
                    await on_tool_call(name, arguments)

                tool_started = monotonic_ms()
                try:
                    output = await tool_executor(name, arguments)
                    ok = not output.get("error")
                except Exception as exc:  # noqa: BLE001 - a tool must never kill the loop
                    output = {"error": f"{type(exc).__name__}: {exc}"}
                    ok = False
                outcome = ToolCallOutcome(
                    call_id=call_id,
                    name=name,
                    arguments=arguments,
                    output=output,
                    ok=ok,
                    duration_ms=elapsed_ms(tool_started),
                )
                outcomes.append(outcome)
                if on_tool_result is not None:
                    await on_tool_result(name, arguments, output)

                conversation.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(output, ensure_ascii=False, default=str)[:60000],
                    }
                )
        else:
            stopped_reason = "iteration_limit"
            logger.warning("%s: hit the %d-iteration tool limit", stage, limit)

        # Final structured conclusion from everything gathered.
        conversation.append(
            {
                "role": "user",
                "content": (
                    "Investigation complete. Using ONLY the evidence you actually gathered "
                    "above, produce the final structured result. Every evidence item must "
                    "reference a file, test or endpoint you genuinely inspected. If the "
                    "evidence is insufficient, say so in the summary and report low confidence."
                ),
            }
        )
        started = monotonic_ms()
        record = AICallRecord(stage=f"{stage}.final", model=self.model)
        records.append(record)
        self.calls.append(record)
        payload: BaseModel | None = None
        last_error = ""
        raw = ""
        for attempt in (1, 2):
            try:
                response = await client.responses.create(
                    **self._base_kwargs(),
                    instructions=instructions,
                    input=conversation,
                    text=text_format_for(final_schema),
                )
            except Exception as exc:  # noqa: BLE001
                record.error = f"{type(exc).__name__}: {exc}"
                record.duration_ms = elapsed_ms(started)
                raise AIError(f"OpenAI request failed during {stage} conclusion: {exc}") from exc
            raw = self._output_text(response)
            tokens_in, tokens_out, reasoning = self._usage(response)
            record.input_tokens += tokens_in
            record.output_tokens += tokens_out
            record.reasoning_tokens += reasoning
            try:
                payload = final_schema.model_validate_json(raw)
                break
            except ValidationError as exc:
                last_error = _format_validation_error(exc)
                if attempt == 1:
                    record.retried = True
                    conversation += [
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": (
                                "That response did not satisfy the schema.\n"
                                f"Validation errors:\n{last_error}\n\nReturn corrected JSON only."
                            ),
                        },
                    ]
        record.duration_ms = elapsed_ms(started)
        if payload is None:
            record.error = last_error
            raise StructuredOutputError(
                f"{stage}: the model's final answer failed schema validation twice; stopping safely.",
                raw=raw,
                errors=[last_error],
            )

        return AgentLoopResult(
            payload=payload,
            tool_calls=outcomes,
            iterations=iterations,
            records=records,
            stopped_reason=stopped_reason,
        )

    # ------------------------------------------------------- public stages --
    async def analyze_failure(self, *, instructions: str, context: str) -> AIDiagnosisResult:
        """Fast, single-shot read of a failure without tool access."""
        return await self._structured(
            stage="analyze_failure",
            instructions=instructions,
            user_input=context,
            schema=AIDiagnosisResult,
        )

    async def investigate_code(
        self,
        *,
        instructions: str,
        context: str,
        tools: list[dict],
        tool_executor: Callable[[str, dict], Awaitable[dict]],
        on_tool_call=None,
        on_tool_result=None,
        max_iterations: int | None = None,
    ) -> AgentLoopResult:
        """Tool-driven investigation ending in a validated diagnosis."""
        return await self.run_tool_loop(
            stage="investigate_code",
            instructions=instructions,
            user_input=context,
            tools=tools,
            tool_executor=tool_executor,
            final_schema=AIDiagnosisResult,
            max_iterations=max_iterations,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
        )

    async def generate_diagnosis(self, *, instructions: str, context: str) -> AIDiagnosisResult:
        return await self._structured(
            stage="generate_diagnosis",
            instructions=instructions,
            user_input=context,
            schema=AIDiagnosisResult,
        )

    async def generate_plan(self, *, instructions: str, context: str) -> AIRepairPlan:
        return await self._structured(
            stage="generate_plan",
            instructions=instructions,
            user_input=context,
            schema=AIRepairPlan,
        )

    async def generate_patch(self, *, instructions: str, context: str) -> AIPatchProposal:
        return await self._structured(
            stage="generate_patch",
            instructions=instructions,
            user_input=context,
            schema=AIPatchProposal,
        )

    async def review_patch(self, *, instructions: str, context: str) -> AIPatchReview:
        return await self._structured(
            stage="review_patch",
            instructions=instructions,
            user_input=context,
            schema=AIPatchReview,
        )

    async def analyze_verification(self, *, instructions: str, context: str) -> AIVerificationAnalysis:
        return await self._structured(
            stage="analyze_verification",
            instructions=instructions,
            user_input=context,
            schema=AIVerificationAnalysis,
        )

    async def analyze_failed_repair(self, *, instructions: str, context: str) -> AIFailedRepairAnalysis:
        return await self._structured(
            stage="analyze_failed_repair",
            instructions=instructions,
            user_input=context,
            schema=AIFailedRepairAnalysis,
        )

    # ---------------------------------------------------------- diagnostics --
    async def check_connectivity(self) -> dict:
        """Settings-page health probe. Never returns any part of the key."""
        if not self.configured:
            return {
                "ok": False,
                "configured": False,
                "model": self.model,
                "detail": "OPENAI_API_KEY is not set",
            }
        client = self._ensure_client()
        started = monotonic_ms()
        try:
            response = await asyncio.wait_for(
                client.responses.create(
                    model=self.model,
                    input=[{"role": "user", "content": "Reply with the single word: ok"}],
                    max_output_tokens=16,
                    store=False,
                ),
                timeout=min(self.settings.openai_timeout_seconds, 45),
            )
        except asyncio.TimeoutError:
            return {
                "ok": False, "configured": True, "model": self.model,
                "detail": "the request timed out", "latency_ms": elapsed_ms(started),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False, "configured": True, "model": self.model,
                "detail": f"{type(exc).__name__}: {exc}"[:400],
                "latency_ms": elapsed_ms(started),
            }
        return {
            "ok": True,
            "configured": True,
            "model": self.model,
            "detail": (self._output_text(response) or "ok").strip()[:80],
            "latency_ms": elapsed_ms(started),
        }

    async def aclose(self) -> None:
        """Close the SDK's connection pool, if one was ever opened."""
        client, self._client = self._client, None
        if client is None:
            return
        try:
            await client.close()
        except Exception as exc:  # noqa: BLE001 - shutdown must not raise
            logger.warning("could not close the OpenAI client cleanly: %s", exc)

    def usage_summary(self) -> dict:
        return {
            "calls": len(self.calls),
            "input_tokens": sum(c.input_tokens for c in self.calls),
            "output_tokens": sum(c.output_tokens for c in self.calls),
            "reasoning_tokens": sum(c.reasoning_tokens for c in self.calls),
            "retries": sum(1 for c in self.calls if c.retried),
            "errors": [c.error for c in self.calls if c.error],
        }


def _serialize_output_item(item) -> dict:
    """Convert an SDK output item back into a plain input dict."""
    if hasattr(item, "model_dump"):
        payload = item.model_dump(exclude_none=True)
    elif isinstance(item, dict):
        payload = dict(item)
    else:  # pragma: no cover - defensive
        payload = {"type": "message", "role": "assistant", "content": str(item)}
    payload.pop("status", None)
    return payload


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors()[:12]:
        location = ".".join(str(part) for part in error.get("loc", ()))
        lines.append(f"- {location or '<root>'}: {error.get('msg')}")
    return "\n".join(lines)


_client_cache: dict[int, OpenAIClient] = {}


def get_openai_client(settings: Settings) -> OpenAIClient:
    """One client per settings object; the SDK client is created lazily.

    The underlying `AsyncOpenAI` owns an HTTP connection pool, so constructing
    one per request would open a fresh TLS connection every time. It is built
    once on first use and reused for the life of the process; `close_clients`
    releases the pool at shutdown.
    """
    key = id(settings)
    client = _client_cache.get(key)
    if client is None or client.model != settings.openai_model:
        client = OpenAIClient(settings)
        _client_cache[key] = client
    return client


async def close_clients() -> None:
    """Release every cached SDK client's connection pool. Called at shutdown."""
    for client in list(_client_cache.values()):
        await client.aclose()
    _client_cache.clear()
