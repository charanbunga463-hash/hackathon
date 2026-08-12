"""One error shape for the whole API.

Every failure — a validation error, a missing project, a rate limit, a timeout,
an unhandled crash — leaves the application as:

    {
      "success": false,
      "error": {"code": "API_TIMEOUT", "message": "...", "request_id": "..."},
      "detail": "..."
    }

`detail` is retained deliberately. It is FastAPI's own field, it is what every
existing client and test reads, and dropping it would be a breaking change that
buys nothing — the envelope is additive.

**What must never appear here**: stack traces, file paths, SQL, connection
strings, API keys, or the text of an internal exception. Anything unrecognised
is answered with a fixed sentence plus the request id, and the real cause is
logged against that id. `SAFE_STATUS` is the allowlist of statuses whose
message was written *for* the caller; everything else is replaced.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..utils.logging import get_logger

logger = get_logger(__name__)

# Status -> stable machine-readable code. Clients switch on `error.code`; the
# message is for humans and may be reworded without breaking anyone.
STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    402: "QUOTA_EXCEEDED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_FAILED",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "UPSTREAM_FAILED",
    503: "UNAVAILABLE",
    504: "API_TIMEOUT",
}

# Statuses whose message was authored for the caller. A 4xx says "your zip is
# too big" or "that code has expired" — text the user needs. A 5xx message is
# whatever the exception happened to say, which is exactly what must not ship.
SAFE_STATUS = frozenset({400, 401, 402, 403, 404, 409, 413, 422, 429})

GENERIC_MESSAGE = {
    500: "Something went wrong on our side. The failure has been logged.",
    502: "An upstream service did not respond correctly.",
    503: "The service is temporarily unavailable. Please try again shortly.",
    504: "The operation exceeded its deadline.",
}


def error_code(status_code: int) -> str:
    if status_code in STATUS_CODES:
        return STATUS_CODES[status_code]
    if 400 <= status_code < 500:
        return "BAD_REQUEST"
    return "INTERNAL_ERROR"


def envelope(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    request_id: str = "",
    extra: dict | None = None,
) -> dict:
    body = {
        "success": False,
        "error": {
            "code": code or error_code(status_code),
            "message": message,
        },
        # FastAPI's native field, kept so existing clients keep working.
        "detail": message,
    }
    if request_id:
        body["error"]["request_id"] = request_id
    if extra:
        body.update(extra)
    return body


def request_id_of(request: Request) -> str:
    from ..runtime.middleware import current_request_id

    state_id = getattr(request.state, "request_id", None)
    return str(state_id or current_request_id() or "")


def _safe_message(status_code: int, raw: str) -> str:
    """The caller's message for a 4xx; a fixed sentence for anything else."""
    if status_code in SAFE_STATUS and raw:
        return raw
    return GENERIC_MESSAGE.get(status_code, GENERIC_MESSAGE[500])


async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    """HTTPException, wrapped — preserving headers the raiser set.

    `Retry-After`, `WWW-Authenticate` and `X-Field` are load-bearing: the
    frontend highlights the offending form input from `X-Field`, and a 429
    without `Retry-After` is unactionable.
    """
    request_id = request_id_of(request)
    raw = exc.detail if isinstance(exc.detail, str) else ""

    if exc.status_code >= 500:
        logger.error(
            "request failed [request_id=%s] %s %s -> %d: %s",
            request_id, request.method, request.url.path, exc.status_code, raw,
        )

    if not isinstance(exc.detail, str):
        # A structured detail (rare, but FastAPI allows any JSON) is passed
        # through untouched rather than being flattened into a string.
        return await http_exception_handler(request, exc)

    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(
            exc.status_code, _safe_message(exc.status_code, raw), request_id=request_id
        ),
        headers=dict(exc.headers or {}),
    )


async def handle_validation_error(request: Request, exc):
    """422 from request-body validation.

    FastAPI's default lists every failing field with its location, which names
    internal model structure. One sentence plus the first field is enough for a
    form to act on.
    """
    request_id = request_id_of(request)
    field = ""
    try:
        first = exc.errors()[0]
        # Drop the "body"/"query" prefix; the client only knows field names.
        parts = [str(p) for p in first.get("loc", ()) if p not in {"body", "query", "path"}]
        field = ".".join(parts)
        message = first.get("msg", "That request is not valid.")
    except Exception:  # noqa: BLE001 - never fail while reporting a failure
        message = "That request is not valid."

    headers = {"X-Field": field} if field else {}
    return JSONResponse(
        status_code=422,
        content=envelope(
            422,
            f"{field}: {message}" if field else message,
            request_id=request_id,
        ),
        headers=headers,
    )


async def handle_unexpected(request: Request, exc: Exception):
    """The last resort. The caller gets a sentence and an id; the log gets all of it."""
    request_id = request_id_of(request)
    logger.exception(
        "unhandled error [request_id=%s] %s %s",
        request_id, request.method, request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content=envelope(500, GENERIC_MESSAGE[500], request_id=request_id),
    )


def install(app) -> None:
    """Register every handler. Order does not matter; FastAPI dispatches by type."""
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected)
