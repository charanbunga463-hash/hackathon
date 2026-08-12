"""Request middleware: correlation, metrics, limits, and failure containment.

These are **pure ASGI** middleware, not Starlette's `BaseHTTPMiddleware`.

That is a deliberate performance decision, made after measuring. Each
`BaseHTTPMiddleware` layer wraps every request in an anyio task group with
memory object streams; with four layers, a trivial `/healthz` returning one dict
peaked at 696 req/s and *degraded* to 259 req/s as concurrency rose to 64 — the
stack itself, not the handler, was the bottleneck. Pure ASGI middleware is a
plain function call around `self.app(scope, receive, send)` with none of that
machinery.

Two layers, in order (outermost first):

    Observability   correlation id, structured logging, metrics, error containment
      -> Gateway    body size, authentication, rate limiting
        -> router
"""

from __future__ import annotations

import contextvars
import time
import uuid

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..services.session_service import SESSION_COOKIE
from ..utils.logging import get_logger
from .identity import (
    ANONYMOUS_TENANT,
    AuthError,
    Principal,
    resolve_principal,
    resolve_session_principal,
)
from .metrics import get_metrics
from .ratelimit import get_rate_limiter

logger = get_logger(__name__)

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
tenant_var: contextvars.ContextVar[str] = contextvars.ContextVar("tenant", default="-")

# Endpoints whose cost justifies the tightest bucket.
HEAVY_PREFIXES = ("/api/repair", "/api/execution", "/api/diagnosis")
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
EXEMPT_PATHS = frozenset({"/api/health", "/healthz", "/readyz", "/metrics"})
SLOW_REQUEST_SECONDS = 2.0

# Endpoints whose responses are deliberately long-lived, so elapsed time says
# nothing about health.
STREAMING_PATHS = ("/api/events",)


def _is_streaming(path: str) -> bool:
    return path.startswith(STREAMING_PATHS)

# The only endpoints reachable without a session. Everything else — including
# every project, execution, repair, report and event route — is closed. This is
# an allowlist on purpose: a new route is protected by default, and forgetting
# to guard one cannot silently expose another user's code.
PUBLIC_AUTH_PATHS = frozenset(
    {
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/verify-otp",
        "/api/auth/resend-otp",
        "/api/auth/forgot-password",
        "/api/auth/verify-reset-otp",
        "/api/auth/reset-password",
        "/api/auth/config",
    }
)
# Rate-limited per client IP rather than per tenant, because the caller does
# not have a tenant yet.
AUTH_PREFIX = "/api/auth"


def _error(status_code: int, message: str, *, retry_after: int | None = None) -> dict:
    """The standard error envelope, for the layers that answer before the router.

    Imported lazily inside the function body would be tidier, but this runs on
    every rejected request; the module-level import is resolved once.
    """
    from ..api.errors import envelope

    extra = {"retry_after": retry_after} if retry_after is not None else None
    return envelope(status_code, message, request_id=current_request_id(), extra=extra)


def _client_ip(scope: Scope, headers: Headers) -> str:
    """Best-effort client address for pre-authentication rate limiting.

    `X-Forwarded-For` is only consulted because this app is documented as
    running behind its own nginx; the left-most entry is the client the proxy
    saw. Direct exposure without a proxy would let a caller spoof it, which is
    why it is used for bucketing alone and never for authorization.
    """
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:64]
    client = scope.get("client")
    return (client[0] if client else "unknown")[:64]


def current_request_id() -> str:
    return request_id_var.get()


def current_tenant() -> str:
    return tenant_var.get()


def active_settings(scope: Scope):
    """Resolve settings per request, not at middleware construction.

    Starlette builds the middleware stack once and caches it, so anything
    captured in `__init__` is frozen for the process lifetime. Reading from
    `app.state` keeps every request on the same configuration the rest of the
    app uses — and makes the stack testable.
    """
    app = scope.get("app")
    configured = getattr(getattr(app, "state", None), "settings", None)
    if configured is not None:
        return configured
    from ..config.settings import get_settings

    return get_settings()


def _scope_state(scope: Scope) -> dict:
    state = scope.setdefault("state", {})
    if state is None:  # pragma: no cover - defensive
        state = scope["state"] = {}
    return state


class ObservabilityMiddleware:
    """Correlation id, metrics and a last-resort error boundary."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming = headers.get("x-request-id") or headers.get("x-correlation-id")
        request_id = (incoming or uuid.uuid4().hex)[:64]
        _scope_state(scope)["request_id"] = request_id
        token = request_id_var.set(request_id)

        metrics = get_metrics()
        metrics.http_in_flight.inc(1.0)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [
                    (b"x-request-id", request_id.encode("latin-1"))
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception(
                "unhandled error [request_id=%s] %s %s",
                request_id, scope.get("method"), scope.get("path"),
            )
            if not response_started:
                status_code = 500
                from ..api.errors import envelope

                response = JSONResponse(
                    status_code=500,
                    content=envelope(
                        500,
                        "Something went wrong on our side. The failure has been logged.",
                        request_id=request_id,
                    ),
                    headers={"X-Request-ID": request_id},
                )
                await response(scope, receive, send)
            else:
                # Headers already went out; the connection is the only signal left.
                raise
        finally:
            elapsed = time.perf_counter() - started
            metrics.http_in_flight.inc(-1.0)
            route = _route_template(scope)
            method = scope.get("method", "GET")
            metrics.http_requests.inc(method=method, path=route, status=str(status_code))
            metrics.http_latency.observe(elapsed, method=method, path=route)
            # The event stream is a long-lived response by design — a 48-second
            # /api/events is a healthy one, not a slow one. Warning on it buries
            # the genuinely slow requests in noise.
            if elapsed > SLOW_REQUEST_SECONDS and not _is_streaming(scope.get("path", "")):
                logger.warning(
                    "slow request [request_id=%s] %s %s took %.2fs",
                    request_id, method, scope.get("path"), elapsed,
                )
            request_id_var.reset(token)


class GatewayMiddleware:
    """Body-size limit, authentication and rate limiting.

    Combined into one layer because they share the same header parse and all
    reject before the router does any work.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")
        state = _scope_state(scope)

        if path in EXEMPT_PATHS or method == "OPTIONS":
            state["principal"] = Principal(tenant="system", label="probe")
            await self.app(scope, receive, send)
            return

        settings = active_settings(scope)
        headers = Headers(scope=scope)

        # --- body size ----------------------------------------------------
        # MAX_PROJECT_SIZE_MB <= 0 means unlimited, and the check is skipped
        # entirely. Without this guard a limit of 0 would compare every body
        # against 0 bytes and reject *every* request that has one — including
        # login and registration.
        raw_length = headers.get("content-length")
        max_bytes = settings.max_project_size_mb * 1024 * 1024
        if raw_length and max_bytes > 0:
            try:
                if int(raw_length) > max_bytes:
                    await JSONResponse(
                        status_code=413,
                        content=_error(
                            413,
                            f"The request body exceeds the {max_bytes / 1e6:.0f} MB limit.",
                        ),
                    )(scope, receive, send)
                    return
            except ValueError:
                pass

        # --- identity -----------------------------------------------------
        # Public auth endpoints are rate limited by IP and then handed straight
        # to the router; they are the only way to obtain a session.
        is_public_auth = path in PUBLIC_AUTH_PATHS
        if is_public_auth:
            client = _client_ip(scope, headers)
            decision = await get_rate_limiter().check(f"ip:{client}", "auth")
            if not decision.allowed:
                get_metrics().rate_limited.inc(bucket="auth")
                logger.warning(
                    "auth rate limited [request_id=%s] %s %s", current_request_id(), method, path
                )
                await JSONResponse(
                    status_code=429,
                    content=_error(
                        429,
                        "Too many attempts. Please wait a moment and try again.",
                        retry_after=decision.retry_after,
                    ),
                    headers=decision.headers(),
                )(scope, receive, send)
                return
            state["principal"] = Principal(tenant=ANONYMOUS_TENANT, label="anonymous")
            state["client_ip"] = client
            await self.app(scope, receive, send)
            return

        session_cookie = _cookie(headers, SESSION_COOKIE) if settings.auth_mode == "user" else None
        try:
            if settings.auth_mode == "user":
                principal = await resolve_session_principal(settings, session_cookie)
            else:
                principal = resolve_principal(
                    auth_mode=settings.auth_mode,
                    authorization=headers.get("authorization"),
                    api_keys=settings.api_key_map,
                    admin_keys=settings.admin_key_set,
                )
        except AuthError as exc:
            if settings.auth_mode == "user":
                headers_out = {}
                if session_cookie:
                    # Clear a cookie we have just refused.
                    #
                    # Without this an expired or revoked session is unrecoverable
                    # in a browser: the frontend's edge middleware sees a cookie
                    # and routes to the app, the app calls /auth/me, gets this
                    # 401 and routes back to /login, where the cookie sends it to
                    # the app again — a loop that leaves the user staring at a
                    # loading spinner with no way out but clearing site data.
                    headers_out["Set-Cookie"] = _expired_session_cookie(settings)
            else:
                headers_out = {"WWW-Authenticate": "Bearer"}
            await JSONResponse(
                status_code=401,
                content=_error(401, str(exc)),
                headers=headers_out,
            )(scope, receive, send)
            return

        state["principal"] = principal
        token = tenant_var.set(principal.tenant)
        try:
            # --- rate limit ------------------------------------------------
            bucket = _bucket_for(path, method)
            decision = await get_rate_limiter().check(principal.tenant, bucket)
            if not decision.allowed:
                get_metrics().rate_limited.inc(bucket=bucket)
                logger.warning(
                    "rate limited [request_id=%s tenant=%s] %s %s",
                    current_request_id(), principal.label, method, path,
                )
                await JSONResponse(
                    status_code=429,
                    content=_error(
                        429,
                        f"Rate limit exceeded for '{bucket}' operations; "
                        f"retry in {decision.retry_after}s.",
                        retry_after=decision.retry_after,
                    ),
                    headers=decision.headers(),
                )(scope, receive, send)
                return

            extra = [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in decision.headers().items()
            ]

            async def send_wrapper(message: Message) -> None:
                if message["type"] == "http.response.start" and extra:
                    message["headers"] = list(message.get("headers", [])) + extra
                await send(message)

            await self.app(scope, receive, send_wrapper if extra else send)
        finally:
            tenant_var.reset(token)


def _expired_session_cookie(settings) -> str:
    """A Set-Cookie that deletes the session cookie.

    Built by hand rather than via `Response.delete_cookie` because this layer
    answers with a bare JSONResponse. The attributes must match the ones the
    cookie was set with, or the browser keeps the original alongside the
    deletion and nothing changes.
    """
    parts = [
        f"{SESSION_COOKIE}=",
        "Path=/",
        "Max-Age=0",
        "Expires=Thu, 01 Jan 1970 00:00:00 GMT",
        "HttpOnly",
        f"SameSite={settings.session_cookie_samesite.capitalize()}",
    ]
    if settings.session_cookie_secure:
        parts.append("Secure")
    return "; ".join(parts)


def _cookie(headers: Headers, name: str) -> str | None:
    """Read one cookie without pulling in a full cookie parser."""
    raw = headers.get("cookie")
    if not raw:
        return None
    for part in raw.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value.strip() or None
    return None


def _bucket_for(path: str, method: str) -> str:
    if path.startswith(AUTH_PREFIX):
        return "auth"
    if method in WRITE_METHODS and path.startswith(HEAVY_PREFIXES):
        return "heavy"
    if method in WRITE_METHODS:
        return "write"
    return "read"


def _route_template(scope: Scope) -> str:
    """Use the route pattern, not the concrete path.

    Recording `/api/projects/prj_a1b2c3` as a label would create unbounded
    cardinality — one time series per project — which is how a metrics backend
    falls over.
    """
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path or "unmatched"
