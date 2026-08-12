"""LOCAL TRUSTED MODE runner.

This executes project code as the backend user with no isolation boundary.
It is the documented fallback for machines without Docker. The only protections
are a hard timeout, a scrubbed environment (no `OPENAI_API_KEY`, no cloud
credentials) and the fact that no shell is ever involved.

Everything that returns a result from this runner is tagged `isolated=False`,
and the UI renders a persistent LOCAL TRUSTED MODE banner. Do not describe this
as a sandbox.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..config.settings import Settings
from ..security.execution_security import (
    SandboxLimits,
    assert_no_secrets,
    scrub_env,
)
from ..utils.logging import get_logger
from .process_manager import ProcessResult, run_process
from .sandbox import Sandbox, SandboxCapabilities

logger = get_logger(__name__)


class LocalRunner(Sandbox):
    kind = "local"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.python = sys.executable

    async def available(self) -> bool:
        return True

    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            kind="local",
            isolated=False,
            network="host (unrestricted)",
            limits=SandboxLimits(
                cpus=0.0,
                memory="unlimited",
                pids=0,
                timeout_seconds=self.settings.execution_timeout_seconds,
                network="host",
                read_only_rootfs=False,
                tmpfs_size="n/a",
            ),
            description=(
                "LOCAL TRUSTED MODE — project code runs directly on the host as the "
                "backend user. Timeouts and environment scrubbing are enforced; "
                "CPU, memory, filesystem and network are NOT restricted."
            ),
            warnings=[
                "No process isolation: uploaded code can read and write host files "
                "the backend user can access.",
                "No network restriction: uploaded code can make outbound connections.",
                "Only run projects you trust. Install Docker and set EXECUTION_MODE=docker "
                "for real isolation.",
            ],
        )

    def _env(self, workspace: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = scrub_env()
        # Make the workspace importable so `from main import app` resolves.
        env["PYTHONPATH"] = str(workspace)
        if extra:
            for key, value in extra.items():
                env[key] = value
        assert_no_secrets(env)
        return env

    async def run_python(
        self,
        args: list[str],
        *,
        workspace: Path,
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> ProcessResult:
        command = [self.python, *args]
        return await run_process(
            command,
            cwd=workspace,
            env=self._env(workspace, extra_env),
            timeout=timeout or self.settings.execution_timeout_seconds,
        )

    def build_python_command(self, args: list[str]) -> list[str]:
        return [self.python, *args]

    def build_env(self, workspace: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
        return self._env(workspace, extra)

    async def ensure_dependencies(self, workspace: Path, packages: list[str]) -> ProcessResult | None:
        """Local mode reuses the backend interpreter, which already has FastAPI.

        We deliberately do NOT pip-install from an uploaded requirements.txt in
        local mode: that would execute arbitrary setup.py code on the host.
        Missing dependencies are reported as a diagnosable failure instead.
        """
        if not packages:
            return None
        missing = await self.missing_packages(workspace, packages)
        if missing:
            logger.warning(
                "local mode: project requires %s which are not installed in the backend "
                "interpreter; not installing automatically",
                ", ".join(missing),
            )
        return None

    async def missing_packages(self, workspace: Path, packages: list[str]) -> list[str]:
        if not packages:
            return []
        probe = (
            "import importlib.util,sys,json;"
            f"names={packages!r};"
            "print(json.dumps([n for n in names if importlib.util.find_spec(n) is None]))"
        )
        result = await self.run_python(["-c", probe], workspace=workspace, timeout=30)
        if result.exit_code != 0:
            return []
        try:
            import json

            return json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return []
