"""API MODE: start the project's API in the sandbox and probe its endpoints.

This is the second failure detector. Where TEST MODE asks "do the project's own
tests pass?", API MODE asks "does the HTTP surface actually work?" — it starts
the app, reads `/openapi.json` for the real contract, calls every discovered
route and records status, latency, body and the server-side traceback for
anything that returns an error status.
"""

from __future__ import annotations

import contextlib
import socket
from pathlib import Path

import httpx

from ..analysis.api_analyzer import concretize_path, routes_from_openapi
from ..analysis.log_analyzer import extract_last_traceback, failure_from_probe
from ..models.execution import ApiRunResult, EndpointProbeResult
from ..models.project import ProjectMetadata, RouteInfo
from ..security.execution_security import assert_no_secrets, scrub_env
from ..utils.logging import get_logger
from ..utils.timestamps import elapsed_ms, monotonic_ms
from .docker_runner import DockerRunner
from .local_runner import LocalRunner
from .process_manager import BackgroundProcess
from .sandbox import Sandbox

logger = get_logger(__name__)

SAFE_PROBE_METHODS = {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}
# Probing is read-oriented by default; write verbs are only called when the
# caller opts in, because the project's data store is real.
DEFAULT_PROBE_METHODS = {"GET", "HEAD", "OPTIONS"}


def find_free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def module_path_for(entry_point: str) -> str:
    """`app/main.py` -> `app.main`."""
    cleaned = entry_point.replace("\\", "/")
    if cleaned.endswith(".py"):
        cleaned = cleaned[:-3]
    return cleaned.strip("/").replace("/", ".")


def build_server_process(
    sandbox: Sandbox, workspace: Path, metadata: ProjectMetadata, port: int
) -> tuple[BackgroundProcess, str]:
    """Build the uvicorn child process for the resolved runner."""
    entry = metadata.entry_point or "main.py"
    module = module_path_for(entry)
    app_object = metadata.app_object or "app"
    target = f"{module}:{app_object}"

    if isinstance(sandbox, DockerRunner):
        args = [
            "-m", "uvicorn", target,
            "--host", "0.0.0.0",          # reachable through the published port
            "--port", str(port),
            "--log-level", "info",
        ]
        command = sandbox.build_run_command(
            args, workspace=workspace, publish=(port, port)
        )
        env = scrub_env()
        assert_no_secrets(env)
        return BackgroundProcess(command, workspace, env), f"http://127.0.0.1:{port}"

    local = sandbox if isinstance(sandbox, LocalRunner) else LocalRunner(sandbox.settings)
    args = [
        "-m", "uvicorn", target,
        "--host", "127.0.0.1",
        "--port", str(port),
        "--log-level", "info",
    ]
    command = local.build_python_command(args)
    env = local.build_env(workspace)
    return BackgroundProcess(command, workspace, env), f"http://127.0.0.1:{port}"


async def wait_for_ready(
    base_url: str,
    process: BackgroundProcess,
    timeout: float,
    client: httpx.AsyncClient,
) -> bool:
    """Poll until the server answers, giving up if the process dies first."""
    import asyncio

    deadline = monotonic_ms() + timeout * 1000
    while monotonic_ms() < deadline:
        if not process.is_running() and process.exit_code is not None:
            return False
        for probe_path in ("/openapi.json", "/docs", "/"):
            try:
                response = await client.get(f"{base_url}{probe_path}", timeout=3.0)
                if response.status_code < 500 or probe_path == "/":
                    return True
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError):
                continue
            except httpx.HTTPError:
                continue
        await asyncio.sleep(0.35)
    return False


def _probe_targets(
    metadata: ProjectMetadata,
    runtime_routes: list[RouteInfo],
    methods: set[str],
) -> list[RouteInfo]:
    source = runtime_routes or metadata.routes
    targets = [
        route
        for route in source
        if route.method.upper() in methods
        and not route.path.startswith(("/docs", "/redoc", "/openapi.json"))
    ]
    return targets


async def probe_endpoints(
    base_url: str,
    routes: list[RouteInfo],
    *,
    timeout: float,
    client: httpx.AsyncClient,
) -> list[EndpointProbeResult]:
    """Call every target endpoint, recording exactly what came back.

    This is the deterministic half of the testing engine: status, latency,
    headers and body are *measured* here. Nothing downstream — including the AI
    layer — may overwrite these values; see `analysis.log_analyzer`.
    """
    results: list[EndpointProbeResult] = []
    for route in routes:
        concrete = concretize_path(route.path)
        url = f"{base_url}{concrete}"
        started = monotonic_ms()
        try:
            response = await client.request(route.method.upper(), url, timeout=timeout)
            snippet = response.text[:4000]
            results.append(
                EndpointProbeResult(
                    method=route.method.upper(),
                    path=route.path,
                    url=url,
                    status_code=response.status_code,
                    ok=response.status_code < 400,
                    latency_ms=elapsed_ms(started),
                    response_snippet=snippet,
                    headers={
                        key: value
                        for key, value in response.headers.items()
                        if key.lower() in {"content-type", "content-length", "server"}
                    },
                )
            )
        except httpx.HTTPError as exc:
            results.append(
                EndpointProbeResult(
                    method=route.method.upper(),
                    path=route.path,
                    url=url,
                    status_code=None,
                    ok=False,
                    latency_ms=elapsed_ms(started),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return results


async def fetch_openapi(
    base_url: str, timeout: float, client: httpx.AsyncClient
) -> dict | None:
    try:
        response = await client.get(f"{base_url}/openapi.json", timeout=timeout)
        if response.status_code == 200:
            return response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return None


async def run_api_probe(
    sandbox: Sandbox,
    workspace: Path,
    metadata: ProjectMetadata,
    *,
    include_write_methods: bool = False,
    only: list[str] | None = None,
    probe_timeout_seconds: float | None = None,
) -> ApiRunResult:
    """Start the API, read its contract, probe it, and normalise every failure.

    `probe_timeout_seconds` overrides the deployment default with the caller's
    own setting (Settings -> API Doctor -> Request timeout). It is clamped
    rather than trusted: an unbounded value here would hold a sandbox open
    indefinitely.
    """
    settings = sandbox.settings
    probe_timeout = (
        max(1.0, min(float(probe_timeout_seconds), 300.0))
        if probe_timeout_seconds
        else float(settings.api_probe_timeout_seconds)
    )
    started = monotonic_ms()
    port = find_free_port()
    result = ApiRunResult(runner=sandbox.kind)

    if isinstance(sandbox, DockerRunner) and not await sandbox.ensure_image():
        result.startup_error = "sandbox image is unavailable; cannot start the API in docker mode"
        result.duration_ms = elapsed_ms(started)
        return result

    process, base_url = build_server_process(sandbox, workspace, metadata, port)
    result.base_url = base_url

    try:
        # One client for the whole run: readiness polling, the OpenAPI fetch and
        # every endpoint call share its connection pool, so the probe opens one
        # connection to the sandbox rather than one per phase. Scoped to the run
        # rather than the application because each run targets a different
        # short-lived sandbox on its own port.
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=probe_timeout
        ) as client:
            await _probe_with(
                client,
                result=result,
                process=process,
                base_url=base_url,
                sandbox=sandbox,
                workspace=workspace,
                metadata=metadata,
                probe_timeout=probe_timeout,
                include_write_methods=include_write_methods,
                only=only,
            )
    finally:
        await process.stop()

    result.duration_ms = elapsed_ms(started)
    logger.info(
        "api probe [%s]: %d endpoints, %d failures",
        sandbox.kind, len(result.probes), len(result.failures),
    )
    return result


async def _probe_with(
    client: httpx.AsyncClient,
    *,
    result: ApiRunResult,
    process: BackgroundProcess,
    base_url: str,
    sandbox: Sandbox,
    workspace: Path,
    metadata: ProjectMetadata,
    probe_timeout: float,
    include_write_methods: bool,
    only: list[str] | None,
) -> None:
    """The run itself, mutating `result` in place.

    Split out so `run_api_probe` keeps one `try/finally` around process
    shutdown; the sandbox must be torn down whether this returns or raises.
    """
    settings = sandbox.settings

    if not await process.start():
        result.startup_error = process.start_error or "failed to start the API process"
        return

    ready = await wait_for_ready(
        base_url, process, settings.api_startup_timeout_seconds, client
    )
    result.startup_stdout = process.stdout[-20000:]
    result.startup_stderr = process.stderr[-20000:]
    result.started = ready

    if not ready:
        combined = f"{process.stdout}\n{process.stderr}"
        result.startup_error = (
            extract_last_traceback(combined)
            or combined.strip()[-4000:]
            or "the API did not become reachable before the startup timeout"
        )
        from ..analysis.log_analyzer import failure_id
        from ..analysis.stacktrace_parser import parse_traceback, severity_for
        from ..models.execution import NormalizedFailure

        parsed = parse_traceback(result.startup_error, workspace)
        culprit = parsed.culprit()

        result.failures.append(
            NormalizedFailure(
                id=failure_id("startup", parsed.error_type, parsed.message),
                error_type=(
                    parsed.error_type
                    if parsed.error_type != "UnknownError"
                    else "StartupError"
                ),
                message=parsed.message or "the API failed to start",
                file=culprit.file if culprit else metadata.entry_point,
                line=culprit.line if culprit else None,
                function=culprit.function if culprit else None,
                severity=severity_for(parsed.error_type),
                traceback=result.startup_error[:12000],
                frames=parsed.frames,
                source="startup",
                raw_output=result.startup_error[:12000],
            )
        )
        return

    schema = await fetch_openapi(base_url, probe_timeout, client)
    result.openapi = schema
    runtime_routes = routes_from_openapi(schema) if schema else []

    methods = set(SAFE_PROBE_METHODS) if include_write_methods else set(DEFAULT_PROBE_METHODS)
    targets = _probe_targets(metadata, runtime_routes, methods)
    if only:
        wanted = {value.strip().upper() for value in only}
        targets = [
            r for r in targets if r.signature.upper() in wanted or r.path.upper() in wanted
        ]

    result.probes = await probe_endpoints(
        base_url, targets, timeout=probe_timeout, client=client
    )
    server_log = f"{process.stdout}\n{process.stderr}"
    result.startup_stdout = process.stdout[-20000:]
    result.startup_stderr = process.stderr[-20000:]

    for probe in result.probes:
        failure = failure_from_probe(probe, server_log=server_log, project_root=workspace)
        if failure is not None:
            result.failures.append(failure)
