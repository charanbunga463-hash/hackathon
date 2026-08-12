"""Sandbox abstraction.

Two implementations exist behind one interface:

  * `DockerRunner` — real isolation: cpu/memory/pid caps, no network, read-only
    root filesystem, no host mounts beyond the project directory, no secrets.
  * `LocalRunner` — LOCAL TRUSTED MODE. It is *not* a sandbox. It limits
    timeouts and strips secrets from the environment, and that is all. Every
    surface that reports execution says so explicitly; the product never claims
    isolation it does not have.
"""

from __future__ import annotations

import abc
import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..config.settings import Settings
from ..security.execution_security import SandboxLimits
from .process_manager import ProcessResult

RunnerKind = Literal["docker", "local"]


@dataclass
class SandboxCapabilities:
    kind: RunnerKind
    isolated: bool
    network: str
    limits: SandboxLimits
    description: str
    warnings: list[str]

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "isolated": self.isolated,
            "network": self.network,
            "limits": self.limits.as_dict(),
            "description": self.description,
            "warnings": self.warnings,
        }


class Sandbox(abc.ABC):
    """Runs untrusted project code. Implementations never take a shell string."""

    kind: RunnerKind

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.limits = SandboxLimits(
            cpus=settings.docker_cpu_limit,
            memory=settings.docker_memory_limit,
            pids=settings.docker_pids_limit,
            timeout_seconds=settings.execution_timeout_seconds,
            network=settings.docker_network,
            read_only_rootfs=settings.docker_read_only_rootfs,
            tmpfs_size=settings.docker_tmpfs_size,
        )

    @abc.abstractmethod
    async def available(self) -> bool:
        ...

    @abc.abstractmethod
    def capabilities(self) -> SandboxCapabilities:
        ...

    @abc.abstractmethod
    async def run_python(
        self,
        args: list[str],
        *,
        workspace: Path,
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> ProcessResult:
        """Run `python <args>` inside the workspace."""

    @abc.abstractmethod
    async def ensure_dependencies(self, workspace: Path, packages: list[str]) -> ProcessResult | None:
        """Best-effort install of the packages the project needs to run."""


# Probing costs a `docker version` subprocess, and the sidebar, the trusted-mode
# banner and the Settings page all ask on every navigation. Without this cache a
# single page load spawned four probes, each of which has to time out when the
# daemon is down. A short TTL keeps the answer honest while collapsing bursts.
PROBE_TTL_SECONDS = 15.0
_probe_cache: dict[str, object] = {"at": 0.0, "state": None, "key": None}
_probe_lock = asyncio.Lock()


def _probe_cache_key(settings: Settings) -> str:
    return f"{settings.execution_mode}|{settings.docker_image}|{settings.docker_network}"


async def probe_execution_state(settings: Settings, *, force: bool = False) -> dict:
    """Determine the ACTUAL execution posture by building the sandbox.

    Everything user-facing that mentions isolation must come from here rather
    than from configuration, because configuration cannot tell you whether the
    Docker daemon is reachable right now.

    Results are cached for `PROBE_TTL_SECONDS`; concurrent callers share one
    probe rather than each spawning their own.
    """
    key = _probe_cache_key(settings)
    now = time.monotonic()
    cached = _probe_cache.get("state")
    if (
        not force
        and cached is not None
        and _probe_cache.get("key") == key
        and now - float(_probe_cache.get("at") or 0.0) < PROBE_TTL_SECONDS
    ):
        return dict(cached)  # type: ignore[arg-type]

    async with _probe_lock:
        # Another caller may have refreshed it while we waited for the lock.
        cached = _probe_cache.get("state")
        now = time.monotonic()
        if (
            not force
            and cached is not None
            and _probe_cache.get("key") == key
            and now - float(_probe_cache.get("at") or 0.0) < PROBE_TTL_SECONDS
        ):
            return dict(cached)  # type: ignore[arg-type]
        state = await _probe_uncached(settings)
        _probe_cache.update({"at": time.monotonic(), "state": state, "key": key})
        return dict(state)


def reset_probe_cache() -> None:
    """Test hook: forget the cached execution posture."""
    _probe_cache.update({"at": 0.0, "state": None, "key": None})


async def _probe_uncached(settings: Settings) -> dict:
    try:
        sandbox = await build_sandbox(settings)
    except RuntimeError as exc:
        return {
            "execution_mode_resolved": "unavailable",
            "execution_isolated": False,
            "sandbox": {
                "kind": settings.execution_mode,
                "isolated": False,
                "error": str(exc),
                "warnings": [str(exc)],
            },
        }
    capabilities = sandbox.capabilities()
    return {
        "execution_mode_resolved": capabilities.kind,
        "execution_isolated": capabilities.isolated,
        "sandbox": capabilities.as_dict(),
    }


async def build_sandbox(settings: Settings, *, prefer: RunnerKind | None = None) -> Sandbox:
    """Resolve the execution mode, falling back to local when docker is absent."""
    from .docker_runner import DockerRunner
    from .local_runner import LocalRunner

    requested = prefer or settings.resolve_execution_mode()
    if requested == "docker":
        docker = DockerRunner(settings)
        if await docker.available():
            return docker
        if settings.execution_mode == "docker":
            # Explicitly configured for docker: do not silently downgrade the
            # security posture, surface it.
            raise RuntimeError(
                "EXECUTION_MODE=docker but the Docker daemon is not reachable. "
                "Start Docker or set EXECUTION_MODE=local to accept LOCAL TRUSTED MODE."
            )
    return LocalRunner(settings)
