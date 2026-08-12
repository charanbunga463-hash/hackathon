"""API Doctor — FastAPI application entry point.

Development:
    uvicorn app.main:app --reload --port 8000

Production (multiple workers require REDIS_URL — see docs/scaling.md):
    gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from .api import errors
from .api.routes import (
    account,
    auth,
    diagnosis,
    events,
    execution,
    health,
    projects,
    reports,
    repair,
)
from .config.settings import get_settings
from .runtime.concurrency import configure_pools, io_bound, pool_stats, shutdown_pools
from .runtime.jobs import init_job_queue
from .runtime.metrics import get_metrics
from .runtime.middleware import GatewayMiddleware, ObservabilityMiddleware
from .runtime.ratelimit import init_rate_limiter
from .runtime.state import init_state_backend, reset_state_backend
from .services.event_service import get_event_bus
from .services.project_service import ProjectError
from .utils.logging import configure_logging, get_logger

logger = get_logger(__name__)

DESCRIPTION = """
**API Doctor** — Detect. Diagnose. Repair. Verify.

An AI agent that detects broken APIs, investigates them against real source code and
test output, proposes a minimal patch, applies it under developer approval, and
verifies the repair by running the project's own test suite.

A repair is reported as **VERIFIED** only when a real test run proves it. The system
distinguishes observed facts, hypotheses, root causes, proposed fixes, test results
and verified results, and never presents one as another.

AI provider: **OpenAI** (Responses API, structured outputs). The API key is read from
the environment, is never sent to the frontend, and is never written into a project.

Heavy work (test runs, API probes, repairs) is queued under admission control. When
the system is at capacity it returns `202` with a job id, or `429` with `Retry-After`
— never an unbounded wait.
"""

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Resolved at startup, not import, so the running configuration is a single
    # object every middleware and route agrees on.
    settings = get_settings()
    app.state.settings = settings
    configure_logging(settings.log_level)
    settings.ensure_directories()

    problems = settings.validate_for_environment()
    if problems:
        for problem in problems:
            logger.critical("unsafe production configuration: %s", problem)
        raise RuntimeError(
            "refusing to start with an unsafe production configuration:\n  - "
            + "\n  - ".join(problems)
        )

    configure_pools(settings.cpu_pool_workers, settings.io_pool_workers)

    # The database comes up before anything that reads it: the stores pick
    # their backend at construction, and a service built first would keep the
    # JSON fallback for the life of the process.
    from .db import close_pool, init_database

    database_ready = await io_bound(
        init_database,
        settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    app.state.database = "postgres" if database_ready else "json"

    state = await init_state_backend(settings.redis_url, namespace=settings.state_namespace)
    init_rate_limiter(settings.rate_table(), state=state, enabled=settings.rate_limit_enabled)
    queue = init_job_queue(settings.queue_limits(), state=state)

    bus = get_event_bus()
    await bus.start(state)

    from .runtime.shared_cache import start_invalidation_listener, stop_invalidation_listener

    await start_invalidation_listener()
    app.state.job_queue = queue
    app.state.state_backend = state

    # The cross-worker approval listener is only meaningful with shared state.
    # Constructing the RepairService here would pin it to this module's settings
    # object and defeat dependency overrides, so it is built only when needed.
    repairs = None
    if state.name != "memory":
        from .api.deps import _project_service
        from .services.repair_service import get_repair_service

        repairs = get_repair_service(settings, _project_service())
        repairs.queue = queue
        await repairs.start_approval_listener()

    mode = settings.resolve_execution_mode()
    metrics = get_metrics()
    metrics.build_info.set(
        1.0,
        version="1.1.0",
        engine="openai" if settings.ai_enabled else "deterministic-offline",
        state=state.name,
        auth=settings.auth_mode,
    )

    logger.info(
        "%s starting (db=%s, state=%s, auth=%s)",
        settings.app_name,
        "postgres" if database_ready else "json files",
        state.name,
        settings.auth_mode,
    )
    logger.info(
        "reasoning engine: %s (model=%s)",
        "openai" if settings.ai_enabled else "deterministic-offline",
        settings.openai_model,
    )
    logger.info("execution mode: %s (configured: %s)", mode, settings.execution_mode)
    logger.info(
        "capacity: %d concurrent job(s), %d per tenant, %d queued max",
        settings.max_concurrent_jobs,
        settings.max_concurrent_jobs_per_tenant,
        settings.max_queued_jobs,
    )
    if mode == "local":
        logger.warning(
            "LOCAL TRUSTED MODE — uploaded project code will run on this host without "
            "isolation. Only load projects you trust."
        )
    if not settings.ai_enabled:
        logger.warning(
            "OPENAI_API_KEY is not set. The deterministic offline engine will be used and "
            "labelled as such; it is not AI output."
        )
    if state.name == "memory" and settings.workers_hint > 1:
        logger.error(
            "%d workers configured with in-memory state: approvals and the event stream "
            "will not work across workers. Set REDIS_URL.",
            settings.workers_hint,
        )

    app.state.ready = True
    try:
        yield
    finally:
        app.state.ready = False
        logger.info("%s draining", settings.app_name)
        if repairs is not None:
            await repairs.stop_approval_listener()
        await stop_invalidation_listener()
        await bus.stop()
        # Let in-flight repairs finish rather than leaving a half-applied patch.
        await queue.drain(timeout=settings.shutdown_drain_seconds)
        # Long-lived clients are released only after the work that uses them has
        # drained, in the reverse order they were opened: AI pool, thread pools,
        # Redis, then the database pool.
        from .ai.openai_client import close_clients as close_ai_clients

        await close_ai_clients()
        shutdown_pools(wait=False)
        await reset_state_backend()
        close_pool()
        logger.info("%s stopped", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Middleware runs bottom-up on the way in: the last added is outermost.
# These are pure ASGI (see runtime/middleware.py) and read `app.state.settings`
# per request rather than capturing it, because Starlette builds and caches this
# stack exactly once.
app.add_middleware(GatewayMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(ObservabilityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # The session cookie has to travel on cross-origin XHR when the frontend is
    # served from its own origin. Credentials require an explicit origin list —
    # the browser refuses to pair them with `*`, and `validate_for_environment`
    # rejects `CORS_ORIGINS=*` in production for the same reason.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-RateLimit-Remaining", "Retry-After", "X-Field"],
)


# Every error leaves the app in one shape; see api/errors.py for what is and is
# not allowed into a response body.
errors.install(app)


@app.exception_handler(ProjectError)
async def project_error_handler(request: Request, exc: ProjectError):
    # These messages are written for the user ("that archive is not a zip"),
    # so they are safe to return verbatim.
    return JSONResponse(
        status_code=400,
        content=errors.envelope(400, str(exc), request_id=errors.request_id_of(request)),
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    # Path/archive/execution security errors all derive from ValueError; surface
    # them as 400s with their message rather than as a 500.
    return JSONResponse(
        status_code=400,
        content=errors.envelope(400, str(exc), request_id=errors.request_id_of(request)),
    )


@app.exception_handler(asyncio.TimeoutError)
async def timeout_handler(request: Request, _exc: asyncio.TimeoutError):
    return JSONResponse(
        status_code=504,
        content=errors.envelope(
            504,
            "The operation exceeded its deadline.",
            code="API_TIMEOUT",
            request_id=errors.request_id_of(request),
        ),
        headers={"Retry-After": "30"},
    )


for router in (
    health.router,
    auth.router,
    account.router,
    projects.router,
    execution.router,
    diagnosis.router,
    repair.router,
    reports.router,
    events.router,
):
    app.include_router(router, prefix="/api")


@app.get("/", tags=["health"])
async def root() -> dict:
    return {
        "name": settings.app_name,
        "tagline": "Detect. Diagnose. Repair. Verify.",
        "docs": "/docs",
        "api": "/api",
        "events": "/api/events",
        "ai_provider": "openai",
    }


@app.get("/healthz", tags=["health"], include_in_schema=False)
async def healthz() -> dict:
    """Liveness: is this process running? Must never depend on a downstream."""
    return {"status": "ok"}


@app.get("/readyz", tags=["health"], include_in_schema=False)
async def readyz(response: Response) -> dict:
    """Readiness: should the load balancer send this worker traffic?

    Goes false while draining, so in-flight repairs finish without new requests
    arriving mid-shutdown.
    """
    from .runtime.jobs import get_job_queue
    from .runtime.state import get_state_backend

    from .db import database_enabled
    from .db import healthy as database_healthy

    state = get_state_backend()
    state_ok = await state.healthy()
    # A worker that cannot reach the database can serve nothing useful, so it
    # should stop receiving traffic rather than answering every request with a
    # 500 until someone notices.
    database_on = database_enabled()
    database_ok = (await io_bound(database_healthy)) if database_on else True
    ready = bool(getattr(app.state, "ready", False)) and state_ok and database_ok
    if not ready:
        response.status_code = 503
    return {
        "ready": ready,
        "database": "postgres" if database_on else "json files",
        "database_healthy": database_ok,
        "state_backend": state.name,
        "state_healthy": state_ok,
        "queue": get_job_queue().stats(),
        "pools": pool_stats(),
    }


@app.get("/metrics", tags=["health"], include_in_schema=False)
async def metrics() -> PlainTextResponse:
    """Prometheus exposition. Unauthenticated by design — scrape from inside only."""
    from .runtime.jobs import get_job_queue

    registry = get_metrics()
    stats = get_job_queue().stats()
    registry.job_queue_depth.set(float(stats["queued"]))
    registry.job_running.set(float(stats["running"]))
    return PlainTextResponse(registry.render(), media_type="text/plain; version=0.0.4")
