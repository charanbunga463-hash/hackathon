"""Policy for running untrusted project code.

Two rules dominate this module:

1. Backend secrets never cross into a child process. `OPENAI_API_KEY` in
   particular is stripped from every environment we build, in both docker and
   local mode. Uploaded code must not be able to read it.
2. The model never supplies a command line. Commands are assembled here from
   fixed templates; the only model-influenced value is a pytest node id, which
   is validated against a strict character allowlist.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

SECRET_ENV_KEYS = {
    "OPENAI_API_KEY",
    "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION",
    "OPENAI_PROJECT",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "DATABASE_URL",
    "SECRET_KEY",
    "API_DOCTOR_ADMIN_TOKEN",
}

SECRET_ENV_SUBSTRINGS = ("SECRET", "TOKEN", "PASSWORD", "APIKEY", "API_KEY", "CREDENTIAL", "PRIVATE_KEY")

# Environment variables a child process legitimately needs on each platform.
_SAFE_PASSTHROUGH = {
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "TEMP", "TMP", "TZ", "LANG", "LC_ALL", "HOME",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "SYSTEMDRIVE", "TERM",
}

PYTEST_NODE_ID = re.compile(r"^[A-Za-z0-9_\-./\[\]:=+ ]{1,300}$")


class ExecutionSecurityError(ValueError):
    """Raised when an execution request violates policy."""


def is_secret_key(key: str) -> bool:
    upper = key.upper()
    if upper in SECRET_ENV_KEYS:
        return True
    return any(token in upper for token in SECRET_ENV_SUBSTRINGS)


def scrub_env(base: dict[str, str] | None = None, *, inherit_path: bool = True) -> dict[str, str]:
    """Build a minimal environment for an untrusted child process."""
    source = os.environ if base is None else base
    env: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if is_secret_key(upper):
            continue
        if upper == "PATH":
            if inherit_path:
                env["PATH"] = value
            continue
        if upper in _SAFE_PASSTHROUGH:
            env[key] = value
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("API_DOCTOR_SANDBOX", "1")
    return env


def assert_no_secrets(env: dict[str, str]) -> None:
    leaked = sorted(k for k in env if is_secret_key(k))
    if leaked:
        raise ExecutionSecurityError(f"refusing to run child process with secrets in env: {leaked}")


def validate_test_selector(selector: str) -> str:
    """Validate a pytest node id before it is passed as an argv element.

    Note this is defence in depth: commands are always run without a shell, so
    metacharacters cannot inject. The allowlist keeps a model from smuggling
    pytest flags (anything starting with `-`) into the argv.
    """
    cleaned = (selector or "").strip()
    if not cleaned:
        raise ExecutionSecurityError("empty test selector")
    if cleaned.startswith("-"):
        raise ExecutionSecurityError(f"test selector may not be a flag: {selector!r}")
    if not PYTEST_NODE_ID.match(cleaned):
        raise ExecutionSecurityError(f"test selector contains unsupported characters: {selector!r}")
    if ".." in cleaned:
        raise ExecutionSecurityError(f"test selector may not traverse directories: {selector!r}")
    return cleaned


@dataclass(frozen=True)
class SandboxLimits:
    """Resource ceilings applied to every sandboxed run."""

    cpus: float = 1.0
    memory: str = "512m"
    pids: int = 128
    timeout_seconds: int = 120
    network: str = "none"
    read_only_rootfs: bool = True
    tmpfs_size: str = "64m"

    def as_dict(self) -> dict:
        return {
            "cpus": self.cpus,
            "memory": self.memory,
            "pids": self.pids,
            "timeout_seconds": self.timeout_seconds,
            "network": self.network,
            "read_only_rootfs": self.read_only_rootfs,
            "tmpfs_size": self.tmpfs_size,
        }
