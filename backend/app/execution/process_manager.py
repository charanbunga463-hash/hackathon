"""Subprocess lifecycle management.

Untrusted code gets a hard timeout and a guaranteed kill. On POSIX the child is
put in its own process group so the whole tree dies; on Windows the equivalent
is a job-less `taskkill /T`. Either way nothing is left running.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..utils.logging import get_logger
from ..utils.timestamps import elapsed_ms, monotonic_ms

logger = get_logger(__name__)

IS_WINDOWS = sys.platform == "win32"
MAX_CAPTURE_BYTES = 400_000


@dataclass
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    command: list[str] = field(default_factory=list)
    cwd: str = ""


def _creation_flags() -> int:
    if IS_WINDOWS:
        return subprocess.CREATE_NEW_PROCESS_GROUP
    return 0


def _preexec():
    if IS_WINDOWS:
        return None
    return os.setsid


def _truncate(data: bytes) -> str:
    if len(data) > MAX_CAPTURE_BYTES:
        head = data[: MAX_CAPTURE_BYTES // 2].decode("utf-8", errors="replace")
        tail = data[-MAX_CAPTURE_BYTES // 2 :].decode("utf-8", errors="replace")
        return f"{head}\n\n...[output truncated: {len(data)} bytes total]...\n\n{tail}"
    return data.decode("utf-8", errors="replace")


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if IS_WINDOWS:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/F", "/T", "/PID", str(process.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(killer.wait(), timeout=10)
        else:
            os.killpg(os.getpgid(process.pid), 15)
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                os.killpg(os.getpgid(process.pid), 9)
    except (ProcessLookupError, PermissionError, asyncio.TimeoutError, OSError) as exc:
        logger.warning("failed to terminate pid %s cleanly: %s", process.pid, exc)
    finally:
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass


def _run_blocking(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    stdin_data: bytes | None,
) -> tuple[int, bytes, bytes, bool]:
    """Blocking subprocess run, for event loops that cannot spawn children."""
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed argv, never a shell
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if stdin_data else subprocess.DEVNULL,
            creationflags=_creation_flags(),
            preexec_fn=_preexec(),
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
        return 127, b"", f"failed to start process: {exc}".encode(), False

    try:
        stdout, stderr = process.communicate(input=stdin_data, timeout=timeout)
        return process.returncode, stdout or b"", stderr or b"", False
    except subprocess.TimeoutExpired:
        _kill_tree_blocking(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except Exception:  # noqa: BLE001
            stdout, stderr = b"", b""
        return process.returncode if process.returncode is not None else -1, stdout, stderr, True


def _kill_tree_blocking(process: "subprocess.Popen") -> None:
    try:
        if IS_WINDOWS:
            subprocess.run(  # noqa: S603 - fixed argv
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True, timeout=10, check=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), 9)
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except OSError:
            pass


async def run_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    stdin_data: bytes | None = None,
) -> ProcessResult:
    """Run a command with no shell, capture output, enforce a hard timeout."""
    started = monotonic_ms()
    logger.info("exec: %s (cwd=%s, timeout=%ss)", " ".join(command[:6]), cwd, timeout)
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
            creationflags=_creation_flags(),
            preexec_fn=_preexec(),
        )
    except NotImplementedError:
        # Some event loops cannot spawn subprocesses at all — notably a Windows
        # SelectorEventLoop, which is what uvicorn's worker processes get in
        # multi-worker mode. Without this fallback every sandboxed test run
        # fails with a bare NotImplementedError the moment you scale past one
        # worker. Run it on a thread instead; the semantics are identical.
        logger.debug("event loop lacks subprocess support; using the threaded runner")
        exit_code, stdout, stderr, timed_out = await asyncio.to_thread(
            _run_blocking, command, cwd, env, timeout, stdin_data
        )
        return ProcessResult(
            exit_code=exit_code,
            stdout=_truncate(stdout),
            stderr=_truncate(stderr),
            duration_ms=elapsed_ms(started),
            timed_out=timed_out,
            command=command,
            cwd=str(cwd),
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
        return ProcessResult(
            exit_code=127,
            stdout="",
            stderr=f"failed to start process: {exc}",
            duration_ms=elapsed_ms(started),
            command=command,
            cwd=str(cwd),
        )

    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=stdin_data), timeout=timeout
        )
    except asyncio.TimeoutError:
        timed_out = True
        await _terminate(process)
        stdout, stderr = b"", b""
        try:
            if process.stdout:
                stdout = await asyncio.wait_for(process.stdout.read(), timeout=2)
            if process.stderr:
                stderr = await asyncio.wait_for(process.stderr.read(), timeout=2)
        except (asyncio.TimeoutError, ValueError, OSError):
            pass

    return ProcessResult(
        exit_code=process.returncode if process.returncode is not None else -1,
        stdout=_truncate(stdout or b""),
        stderr=_truncate(stderr or b""),
        duration_ms=elapsed_ms(started),
        timed_out=timed_out,
        command=command,
        cwd=str(cwd),
    )


class BackgroundProcess:
    """A long-lived child (an API server) with streamed output capture."""

    def __init__(self, command: list[str], cwd: Path, env: dict[str, str]) -> None:
        self.command = command
        self.cwd = cwd
        self.env = env
        self.process: asyncio.subprocess.Process | None = None
        self._stdout_chunks: list[str] = []
        self._stderr_chunks: list[str] = []
        self._pumps: list[asyncio.Task] = []
        self._start_error: str | None = None

    async def start(self) -> bool:
        try:
            self.process = await asyncio.create_subprocess_exec(  # noqa: S603
                *self.command,
                cwd=str(self.cwd),
                env=self.env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                creationflags=_creation_flags(),
                preexec_fn=_preexec(),
            )
        except NotImplementedError:
            # API MODE needs a long-lived child with streamed output, which the
            # threaded fallback cannot provide. Fail with a clear, actionable
            # message rather than a bare NotImplementedError.
            self._start_error = (
                "this event loop cannot spawn subprocesses, so API mode is unavailable. "
                "On Windows this happens in uvicorn multi-worker mode; use TEST mode, "
                "run a single worker, or deploy the backend in a Linux container."
            )
            return False
        except (FileNotFoundError, PermissionError, OSError) as exc:
            self._start_error = f"failed to start process: {exc}"
            return False
        self._pumps = [
            asyncio.create_task(self._pump(self.process.stdout, self._stdout_chunks)),
            asyncio.create_task(self._pump(self.process.stderr, self._stderr_chunks)),
        ]
        return True

    async def _pump(self, stream, sink: list[str]) -> None:
        if stream is None:
            return
        total = 0
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                if total < MAX_CAPTURE_BYTES:
                    text = line.decode("utf-8", errors="replace")
                    sink.append(text)
                    total += len(line)
        except (asyncio.CancelledError, ValueError, OSError):
            return

    @property
    def stdout(self) -> str:
        return "".join(self._stdout_chunks)

    @property
    def stderr(self) -> str:
        return "".join(self._stderr_chunks)

    @property
    def start_error(self) -> str | None:
        return self._start_error

    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def exit_code(self) -> int | None:
        return self.process.returncode if self.process else None

    async def stop(self) -> None:
        if self.process is not None:
            await _terminate(self.process)
        for pump in self._pumps:
            pump.cancel()
        for pump in self._pumps:
            try:
                await pump
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._pumps = []

    async def __aenter__(self) -> "BackgroundProcess":
        await self.start()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.stop()
