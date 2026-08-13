"""Application configuration.

Every tunable is read from the environment. Nothing about the AI provider,
model, sandbox limits or upload budget is hard-coded at a call site.
"""

from __future__ import annotations

import functools
import shutil
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent

ExecutionMode = Literal["auto", "docker", "local"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- app ---
    app_name: str = "API Doctor"
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # ------------------------------------------------------------ storage ---
    data_dir: Path = REPO_ROOT / "data"

    # ------------------------------------------------------------- openai ---
    # The key is read from the environment only. It is never written to any
    # generated project file and never sent to the frontend.
    openai_api_key: str | None = Field(default=None, repr=False)
    # The ONE place a model name is chosen. Every call site reads
    # `settings.openai_model`; no module hard-codes a model. Override with
    # OPENAI_MODEL in the environment.
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None
    # gpt-4o-mini answers in seconds, not minutes. A 180 s ceiling was sized for
    # a reasoning model and only serves to hold a worker's connection open long
    # after the call is beyond saving.
    openai_timeout_seconds: float = 60.0
    openai_max_output_tokens: int = 8000
    openai_max_retries: int = 2
    # Only sent to models that actually accept a reasoning parameter; see
    # OpenAIClient._supports_reasoning. Ignored by gpt-4o-mini.
    openai_reasoning_effort: str = "medium"
    # Hard ceiling on the agentic tool loop, so one repair cannot spin forever.
    agent_max_tool_iterations: int = 14
    agent_max_tool_calls_per_iteration: int = 4

    # ---------------------------------------------------------- execution ---
    execution_mode: ExecutionMode = "auto"
    execution_timeout_seconds: int = 180
    docker_image: str = "python:3.12-slim"
    docker_cpu_limit: float = 1.0
    docker_memory_limit: str = "512m"
    docker_pids_limit: int = 128
    docker_network: str = "none"
    docker_tmpfs_size: str = "128m"
    docker_read_only_rootfs: bool = True
    api_probe_timeout_seconds: int = 30
    api_startup_timeout_seconds: int = 25

    # ------------------------------------------------------------- upload ---
    # SIZE LIMITS ARE OFF BY DEFAULT: 0 (or any value <= 0) means unlimited.
    # A project of any size may be imported.
    #
    # This is safe to do only because the upload path streams: the request body
    # goes straight to a staging file and archive members are extracted in 64 KB
    # chunks, so peak memory is a fixed buffer rather than the size of the file.
    # Set a positive value here to reimpose a ceiling.
    max_project_size_mb: int = 0        # the uploaded archive
    max_extracted_size_mb: int = 0      # everything it expands to
    max_file_size_mb: int = 0           # any single member
    # NOT a size limit, and deliberately still enforced: a few million tiny
    # entries exhausts inodes and stalls the filesystem regardless of bytes.
    # Raise it if you genuinely have a larger tree; node_modules/.git/.venv are
    # skipped before this is counted.
    max_file_count: int = 200_000
    # NOT a size limit either. This is the zip-bomb guard — it catches an
    # archive whose *declared* size is small but which expands enormously, which
    # no byte ceiling can detect ahead of time.
    max_compression_ratio: float = 120.0

    # ------------------------------------------------------------- repair ---
    max_repair_attempts: int = 3
    require_approval: bool = True
    max_patch_files: int = 5
    max_patch_edits: int = 12
    max_patch_lines_changed: int = 120
    keep_snapshots: int = 20

    # --------------------------------------------------------- identity ----
    # `user`   — email + password accounts with OTP verification. Each account
    #            is its own tenant. This is the product default.
    # `apikey` — `Authorization: Bearer <key>`, for machine callers and CI.
    # `open`   — single implicit tenant, no authentication. Local development
    #            only; refused when app_env=production, because it would expose
    #            every user's uploaded code to every other user.
    auth_mode: Literal["open", "apikey", "user"] = "user"
    api_keys: str = Field(default="", repr=False)
    admin_api_keys: str = Field(default="", repr=False)

    # Signs OTP digests and is mixed into other derived secrets. Generated per
    # process when unset, which is fine for one dev worker and wrong for any
    # deployment: a restart or a second worker would invalidate live codes.
    secret_key: str = Field(default="", repr=False)

    # Sessions. Idle timeout slides while the user works; the absolute lifetime
    # never extends, so a stolen cookie cannot be kept alive indefinitely.
    session_idle_timeout_seconds: int = 60 * 60 * 12
    session_absolute_lifetime_seconds: int = 60 * 60 * 24 * 14
    session_cookie_secure: bool = False
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # Open registration. Turn off to freeze the user list on a private instance.
    allow_registration: bool = True

    # ------------------------------------------------------------- otp -----
    otp_ttl_seconds: int = 600
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_max_sends_per_hour: int = 5
    # How long the "this code was verified" ticket is good for, i.e. how long
    # the user has to choose a new password after passing the reset OTP.
    otp_ticket_ttl_seconds: int = 900

    # ------------------------------------------------------------ email -----
    # Any SMTP provider. Unset SMTP_HOST logs messages instead of sending them,
    # which is refused in production when accounts are enabled.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: float = 5.0

    # --------------------------------------------------------- database ----
    # Neon (or any Postgres) is the system of record: users, projects, repair
    # sessions and execution records. Unset -> the on-disk JSON stores, which
    # are fine on a laptop and wrong anywhere the filesystem is not shared.
    # Project *workspaces* always stay on disk; a row cannot be a directory
    # that pytest runs in.
    database_url: str | None = Field(default=None, repr=False)
    db_pool_min_size: int = 1
    # Neon caps concurrent connections; keep this small and point DATABASE_URL
    # at the `-pooler` host when running more than one worker.
    db_pool_max_size: int = 8
    # Read-through cache TTL for the hottest owner-scoped queries.
    db_cache_ttl_seconds: float = 5.0

    # ------------------------------------------------------ shared state ----
    # Unset -> in-memory (correct for exactly one worker). Set -> Redis, which
    # is what makes approvals and SSE work across workers.
    redis_url: str | None = None
    state_namespace: str = "apidoctor"

    # ------------------------------------------------------- concurrency ----
    # Heavy jobs run containers and test suites; these are the real capacity
    # limits of the box, not of the HTTP layer.
    max_concurrent_jobs: int = 4
    max_concurrent_jobs_per_tenant: int = 1
    max_queued_jobs: int = 200
    max_queued_jobs_per_tenant: int = 5
    job_timeout_seconds: float = 1800.0
    cpu_pool_workers: int | None = None
    io_pool_workers: int | None = None
    shutdown_drain_seconds: float = 30.0

    # ------------------------------------------------------- rate limits ----
    rate_limit_enabled: bool = True
    rate_limit_read_per_minute: int = 300
    rate_limit_write_per_minute: int = 30
    rate_limit_heavy_per_minute: int = 10
    # Login, registration and OTP. Bucketed per client IP rather than per
    # tenant: the caller has no tenant yet, so a tenant bucket would be one
    # shared pool that any attacker could exhaust for every other user.
    rate_limit_auth_per_minute: int = 10

    # ------------------------------------------------------------ quotas ----
    max_projects_per_tenant: int = 25
    # 0 means unlimited, matching the upload settings above. A storage cap here
    # would otherwise reinstate by the back door the size limit that
    # MAX_PROJECT_SIZE_MB removes.
    max_storage_per_tenant_mb: int = 0

    # -------------------------------------------------------------- sse -----
    max_sse_clients: int = 1000
    sse_heartbeat_seconds: float = 15.0

    # -------------------------------------------------------------- cache ---
    # Read aggregates (dashboard, history, project list, file tree, system) are
    # polled constantly and scan disk. A short TTL plus single-flight turns a
    # thundering herd into one scan; set to 0 to disable.
    aggregate_cache_seconds: float = 2.0

    # ------------------------------------------------------- offline mode ---
    # When no API key is configured the orchestrator falls back to a
    # deterministic rule engine so the pipeline stays demoable. It is always
    # labelled as such in the API and the UI; it is never presented as AI output.
    allow_offline_engine: bool = True

    @field_validator("secret_key", mode="after")
    @classmethod
    def _generate_dev_secret(cls, value: str) -> str:
        """Never run with an empty signing secret.

        A generated per-process key is correct for one dev worker and wrong
        everywhere else: a restart invalidates outstanding OTPs, and a second
        worker cannot verify the first one's codes. `validate_for_environment`
        makes SECRET_KEY mandatory in production for exactly that reason.
        """
        if value and value.strip():
            return value.strip()
        import secrets as _secrets

        return _secrets.token_urlsafe(48)

    @field_validator("data_dir", mode="before")
    @classmethod
    def _expand(cls, value):
        if value is None:
            return value
        return Path(str(value)).expanduser()

    @field_validator(
        "openai_api_key",
        "openai_base_url",
        "redis_url",
        "database_url",
        "cpu_pool_workers",
        "io_pool_workers",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value):
        """Treat an empty value in a .env file as "not configured".

        `.env` files have no way to express None: you write `CPU_POOL_WORKERS=`
        and get the empty string. Without this, every optional setting left
        blank — which is exactly what `.env.example` tells people to do —
        fails validation and the app refuses to start.
        """
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    # ------------------------------------------------------------ helpers ---
    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @functools.cached_property
    def api_key_map(self) -> dict[str, str]:
        from ..runtime.identity import parse_api_keys

        return parse_api_keys(self.api_keys)

    @functools.cached_property
    def admin_key_set(self) -> set[str]:
        from ..runtime.identity import parse_api_keys

        return set(parse_api_keys(self.admin_api_keys))

    def validate_for_environment(self) -> list[str]:
        """Refuse configurations that are unsafe for the declared environment.

        Returned strings are fatal errors. This runs at startup so a misdeployed
        instance fails loudly instead of quietly serving everyone's code to
        everyone.
        """
        problems: list[str] = []
        if not self.is_production:
            return problems

        import os

        if self.auth_mode == "open":
            problems.append(
                "AUTH_MODE=open in production would let any caller read, repair and delete "
                "every tenant's projects. Set AUTH_MODE=user (accounts) or apikey."
            )
        elif self.auth_mode == "apikey" and not self.api_key_map:
            problems.append("AUTH_MODE=apikey but API_KEYS is empty, so no caller can authenticate.")

        if self.accounts_enabled:
            if not os.getenv("SECRET_KEY", "").strip():
                problems.append(
                    "AUTH_MODE=user requires SECRET_KEY. Without it each worker generates its "
                    "own, so OTP codes issued by one worker cannot be verified by another and "
                    "a restart invalidates every code in flight."
                )
            elif len(self.secret_key) < 32:
                problems.append("SECRET_KEY must be at least 32 characters.")
            if not self.smtp_host:
                problems.append(
                    "AUTH_MODE=user requires SMTP_HOST. Without it verification codes are "
                    "written to the log instead of being emailed, so nobody can register."
                )
            if not self.redis_url:
                problems.append(
                    "AUTH_MODE=user requires REDIS_URL. Sessions, OTP codes and their rate "
                    "limits live in shared state; in-memory state loses them on restart and "
                    "does not work across workers."
                )
            if not self.session_cookie_secure:
                problems.append(
                    "SESSION_COOKIE_SECURE must be true in production so the session cookie "
                    "is never sent over plain HTTP."
                )

        weak = [key for key in self.api_key_map if len(key) < 24]
        if weak:
            problems.append(
                f"{len(weak)} API key(s) are shorter than 24 characters; use high-entropy keys."
            )

        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS=* is not acceptable in production.")

        if self.execution_mode == "local":
            problems.append(
                "EXECUTION_MODE=local runs untrusted uploaded code on the host with no "
                "isolation. Production must use EXECUTION_MODE=docker."
            )

        if not self.database_url:
            problems.append(
                "DATABASE_URL is required in production. Without it accounts and projects "
                "are written to one container's filesystem, so a second replica sees a "
                "different world and a redeploy loses everything."
            )

        if not self.redis_url and self.workers_hint > 1:
            problems.append(
                "Multiple workers are configured without REDIS_URL. Approvals and the event "
                "stream would break across workers. Configure Redis or run a single worker."
            )
        return problems

    @property
    def workers_hint(self) -> int:
        """How many workers the process manager was told to run, if it said so."""
        import os

        for name in ("WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS"):
            raw = os.getenv(name)
            if raw and raw.isdigit():
                return int(raw)
        return 1

    def queue_limits(self):
        from ..runtime.jobs import QueueLimits

        return QueueLimits(
            max_concurrent_global=self.max_concurrent_jobs,
            max_concurrent_per_tenant=self.max_concurrent_jobs_per_tenant,
            max_queued=self.max_queued_jobs,
            max_queued_per_tenant=self.max_queued_jobs_per_tenant,
            job_timeout_seconds=self.job_timeout_seconds,
        )

    def rate_table(self):
        from ..runtime.ratelimit import Rate

        return {
            "read": Rate(capacity=self.rate_limit_read_per_minute, per_seconds=60),
            "write": Rate(capacity=self.rate_limit_write_per_minute, per_seconds=60),
            "heavy": Rate(capacity=self.rate_limit_heavy_per_minute, per_seconds=60),
            "auth": Rate(capacity=self.rate_limit_auth_per_minute, per_seconds=60),
        }

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def users_dir(self) -> Path:
        return self.data_dir / "users"

    @property
    def accounts_enabled(self) -> bool:
        return self.auth_mode == "user"

    @property
    def email_transport(self) -> str:
        if not self.smtp_host:
            return "console"
        # SendGrid hosts go over the HTTPS Web API, since PaaS firewalls (Render,
        # Fly, Heroku) block outbound SMTP ports and the SMTP connect just hangs.
        if self.smtp_host.strip().lower().endswith("sendgrid.net"):
            return "sendgrid-api"
        return "smtp"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def docker_available(self) -> bool:
        return shutil.which("docker") is not None

    def resolve_execution_mode(self) -> Literal["docker", "local"]:
        """The mode we INTEND to use, based on configuration and CLI presence.

        This is not proof of isolation: the Docker CLI can be installed while the
        daemon is down, in which case `build_sandbox` falls back to local. Only a
        successful sandbox probe may be reported as isolated — see
        `public_system_info`, whose `execution_isolated` is deliberately False
        until a caller that has probed overrides it.
        """
        if self.execution_mode == "docker":
            return "docker"
        if self.execution_mode == "local":
            return "local"
        return "docker" if self.docker_available else "local"

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.projects_dir,
            self.uploads_dir,
            self.reports_dir,
            self.users_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def public_system_info(self) -> dict:
        """Everything the Settings page shows. Contains no credentials."""
        resolved_mode = self.resolve_execution_mode()
        return {
            "app_name": self.app_name,
            "app_env": self.app_env,
            "ai_provider": "openai",
            "openai_model": self.openai_model,
            "openai_configured": self.ai_enabled,
            "openai_key_hint": _key_hint(self.openai_api_key),
            "openai_base_url": self.openai_base_url or "https://api.openai.com/v1 (default)",
            "reasoning_effort": self.openai_reasoning_effort,
            "max_output_tokens": self.openai_max_output_tokens,
            "agent_max_tool_iterations": self.agent_max_tool_iterations,
            "reasoning_engine": "openai" if self.ai_enabled else ("deterministic-offline" if self.allow_offline_engine else "disabled"),
            "execution_mode_configured": self.execution_mode,
            "execution_mode_intended": resolved_mode,
            # Not probed here — this method is synchronous and reaching the Docker
            # daemon is an I/O call. Claiming isolation we have not verified is the
            # one thing this product must never do, so both of these start at the
            # safe value and are overridden by `probe_execution_state()`.
            "execution_mode_resolved": "local",
            "execution_isolated": False,
            # CLI presence only. The daemon may still be down, in which case the
            # sandbox falls back to local — so this must not be read as "the
            # sandbox is available". `/api/system` adds the probed truth under
            # "sandbox", and that is what the UI shows as the isolation status.
            "docker_cli_present": self.docker_available,
            "docker_image": self.docker_image,
            "sandbox_limits": {
                "cpus": self.docker_cpu_limit,
                "memory": self.docker_memory_limit,
                "pids": self.docker_pids_limit,
                "network": self.docker_network,
                "read_only_rootfs": self.docker_read_only_rootfs,
                "timeout_seconds": self.execution_timeout_seconds,
            },
            # `None` means unlimited, so a client renders "Unlimited" rather
            # than the literal "0 MB", which reads as "nothing may be uploaded".
            "upload_limits": {
                "max_project_size_mb": self.max_project_size_mb or None,
                "max_extracted_size_mb": self.max_extracted_size_mb or None,
                "max_file_size_mb": self.max_file_size_mb or None,
                "max_file_count": self.max_file_count or None,
                "unlimited": self.max_project_size_mb <= 0,
            },
            "repair": {
                "max_attempts": self.max_repair_attempts,
                "require_approval": self.require_approval,
                "max_patch_files": self.max_patch_files,
                "max_patch_lines_changed": self.max_patch_lines_changed,
            },
            "data_dir": str(self.data_dir),
            "auth_mode": self.auth_mode,
            "multi_tenant": self.auth_mode != "open",
            "accounts_enabled": self.accounts_enabled,
            "allow_registration": self.allow_registration,
            # Whether codes are actually emailed. Never the credentials.
            "email_transport": self.email_transport,
            "shared_state": "redis" if self.redis_url else "in-memory (single worker only)",
            "database": "postgres" if self.database_url else "json files (single node only)",
            "concurrency": {
                "max_concurrent_jobs": self.max_concurrent_jobs,
                "max_concurrent_jobs_per_tenant": self.max_concurrent_jobs_per_tenant,
                "max_queued_jobs": self.max_queued_jobs,
                "job_timeout_seconds": self.job_timeout_seconds,
            },
            "rate_limits": {
                "enabled": self.rate_limit_enabled,
                "read_per_minute": self.rate_limit_read_per_minute,
                "write_per_minute": self.rate_limit_write_per_minute,
                "heavy_per_minute": self.rate_limit_heavy_per_minute,
            },
            "quotas": {
                "max_projects_per_tenant": self.max_projects_per_tenant,
                "max_storage_per_tenant_mb": self.max_storage_per_tenant_mb,
            },
        }


def _key_hint(key: str | None) -> str | None:
    """A non-reversible hint so an operator can tell *which* key is loaded."""
    if not key:
        return None
    if len(key) <= 8:
        return "set"
    return f"{key[:3]}...{key[-4:]}"


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
