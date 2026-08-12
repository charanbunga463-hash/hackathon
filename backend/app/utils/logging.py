"""Application logging setup.

Single entry point so every module logs through the same handler and format.
Secrets are scrubbed defensively: an API key must never reach a log file.
"""

from __future__ import annotations

import logging
import os
import re
import sys

_CONFIGURED = False

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)([A-Za-z0-9_\-]{8,})"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-]{8,})"),
]


def scrub(text: str) -> str:
    """Remove anything that looks like a credential from a string."""
    if not text:
        return text
    out = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            out = pattern.sub(lambda m: f"{m.group(1)}***REDACTED***", out)
        else:
            out = pattern.sub("***REDACTED***", out)
    return out


class _ScrubbingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return scrub(super().format(record))


def configure_logging(level: str | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    resolved = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _ScrubbingFormatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(resolved)
    # Uvicorn access logs are noisy while SSE streams are open.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
