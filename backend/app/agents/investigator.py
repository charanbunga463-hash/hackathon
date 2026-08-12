"""Investigation stage — gather evidence about a failure.

With OpenAI configured the model drives a controlled tool loop. Without it, the
backend performs the same deterministic evidence sweep the ranker would suggest,
so downstream stages always receive a populated `Investigation` record.
"""

from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

from ..ai.context_builder import as_prompt_json, build_failure_context, build_retry_context
from ..ai.openai_client import AgentLoopResult, OpenAIClient
from ..ai.schemas import AIDiagnosisResult
from ..analysis.relevance_ranker import rank_files
from ..models.diagnosis import Investigation, InvestigationStep
from ..models.execution import NormalizedFailure, TestRunResult
from ..models.project import ProjectMetadata
from ..utils.logging import get_logger
from ..utils.timestamps import utcnow_iso
from .offline_engine import ENGINE_NAME
from .prompts import load_prompt
from .tools import (
    ToolContext,
    execute_tool,
    investigation_tool_schemas,
    summarize_tool_result,
)

logger = get_logger(__name__)


async def investigate_with_ai(
    client: OpenAIClient,
    ctx: ToolContext,
    failure: NormalizedFailure,
    *,
    test_run: TestRunResult | None,
    previous_attempts: list[dict] | None = None,
    retry_guidance: str = "",
    on_tool_call: Callable[[str, dict], Awaitable[None]] | None = None,
    on_tool_result: Callable[[str, dict, dict], Awaitable[None]] | None = None,
) -> tuple[Investigation, AIDiagnosisResult]:
    """Model-driven investigation. Returns the record and the model's diagnosis."""
    ranked = rank_files(ctx.workspace, failure, ctx.metadata)
    context = build_failure_context(
        ctx.workspace, ctx.metadata, failure, test_run=test_run, openapi=ctx.openapi, ranked=ranked
    )
    context["ranked_candidates"] = [entry.as_dict() for entry in ranked]
    if previous_attempts:
        context["retry"] = build_retry_context(previous_attempts)
    if retry_guidance:
        context["retry_guidance"] = retry_guidance

    investigation = Investigation(failure_id=failure.id, engine="openai")
    steps: list[InvestigationStep] = []

    async def record_call(name: str, arguments: dict) -> None:
        if on_tool_call is not None:
            await on_tool_call(name, arguments)

    async def record_result(name: str, arguments: dict, output: dict) -> None:
        index = len(steps) + 1
        summary = summarize_tool_result(name, output)
        steps.append(
            InvestigationStep(
                index=index,
                tool=name,
                arguments=arguments,
                result_summary=summary,
                ok=not output.get("error"),
            )
        )
        if name in {"read_file", "read_file_range"} and output.get("path"):
            if output["path"] not in investigation.files_read:
                investigation.files_read.append(output["path"])
        if name == "search_code" and arguments.get("query"):
            investigation.searches.append(str(arguments["query"]))
        if on_tool_result is not None:
            await on_tool_result(name, arguments, output)

    prompt = load_prompt("investigation")
    result: AgentLoopResult = await client.investigate_code(
        instructions=prompt,
        context=as_prompt_json(context),
        tools=investigation_tool_schemas(allow_execution=True),
        tool_executor=lambda name, args: execute_tool(ctx, name, args),
        on_tool_call=record_call,
        on_tool_result=record_result,
    )

    investigation.steps = steps
    investigation.iterations = result.iterations
    investigation.finished_at = utcnow_iso()
    if result.stopped_reason == "iteration_limit":
        investigation.notes.append(
            "the investigation hit the configured tool-iteration limit and concluded early"
        )
    diagnosis = result.payload
    assert isinstance(diagnosis, AIDiagnosisResult)
    return investigation, diagnosis


async def investigate_offline(
    ctx: ToolContext,
    failure: NormalizedFailure,
    *,
    on_step: Callable[[str, dict, dict], Awaitable[None]] | None = None,
) -> Investigation:
    """Deterministic evidence sweep: the same tools, driven by the ranker."""
    investigation = Investigation(failure_id=failure.id, engine=ENGINE_NAME)
    ranked = rank_files(ctx.workspace, failure, ctx.metadata)

    plan: list[tuple[str, dict]] = [("get_stack_trace", {}), ("inspect_project", {})]
    for entry in ranked[:4]:
        if entry.focus_line:
            plan.append(
                (
                    "read_file_range",
                    {
                        "path": entry.path,
                        "start_line": max(1, entry.focus_line - 25),
                        "end_line": entry.focus_line + 25,
                    },
                )
            )
        else:
            plan.append(("read_file", {"path": entry.path}))
    if failure.test and "::" in failure.test:
        plan.append(("inspect_tests", {"path": failure.test.split("::")[0]}))
    if failure.endpoint:
        method, _, path = failure.endpoint.partition(" ")
        plan.append(("inspect_route", {"method": method, "path": path}))
    for token in _search_tokens(failure)[:2]:
        plan.append(("search_code", {"query": token, "regex": False, "path_glob": ""}))

    for index, (name, arguments) in enumerate(plan, start=1):
        output = await execute_tool(ctx, name, arguments)
        investigation.steps.append(
            InvestigationStep(
                index=index,
                tool=name,
                arguments=arguments,
                result_summary=summarize_tool_result(name, output),
                ok=not output.get("error"),
            )
        )
        if name in {"read_file", "read_file_range"} and output.get("path"):
            if output["path"] not in investigation.files_read:
                investigation.files_read.append(output["path"])
        if name == "search_code":
            investigation.searches.append(str(arguments.get("query", "")))
        if on_step is not None:
            await on_step(name, arguments, output)

    investigation.iterations = len(plan)
    investigation.finished_at = utcnow_iso()
    investigation.notes.append(
        "deterministic evidence sweep (no OPENAI_API_KEY configured); file selection came "
        "from the relevance ranker rather than model reasoning"
    )
    return investigation


def _search_tokens(failure: NormalizedFailure) -> list[str]:
    from ..analysis.code_search import extract_identifiers, extract_quoted_strings

    tokens = extract_quoted_strings(failure.message)
    if not tokens:
        tokens = extract_identifiers(failure.message)
    if not tokens and failure.function:
        tokens = [failure.function]
    return [token for token in tokens if len(token) >= 3]


def build_context(
    workspace: Path,
    metadata: ProjectMetadata,
    failure: NormalizedFailure,
    *,
    test_run: TestRunResult | None = None,
    openapi: dict | None = None,
) -> dict:
    return build_failure_context(
        workspace, metadata, failure, test_run=test_run, openapi=openapi
    )
