"""Health, system info and provider connectivity."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...ai.openai_client import get_openai_client
from ...config.settings import Settings
from ...execution.sandbox import probe_execution_state
from ...runtime.cache import get_cache
from ...utils.timestamps import utcnow_iso
from ..deps import settings_dep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: Settings = Depends(settings_dep)) -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "time": utcnow_iso(),
    }


@router.get("/system")
async def system(settings: Settings = Depends(settings_dep)) -> dict:
    """Everything the Settings page shows. Contains no credentials.

    The execution posture is *probed*, not read from configuration: a present
    Docker CLI with a stopped daemon must never be reported as an isolated
    sandbox.
    """
    async def build() -> dict:
        info = settings.public_system_info()
        info.update(await probe_execution_state(settings))
        return info

    # Every page in the UI reads this, and it probes the Docker daemon.
    info = await get_cache().get_or_compute(
        ("system",), build, ttl=settings.aggregate_cache_seconds
    )
    info = dict(info)
    info["generated_at"] = utcnow_iso()
    return info


@router.get("/system/ai")
async def ai_status(settings: Settings = Depends(settings_dep)) -> dict:
    """Live provider check. Never returns any part of the API key."""
    client = get_openai_client(settings)
    result = await client.check_connectivity()
    result["provider"] = "openai"
    result["offline_engine_available"] = settings.allow_offline_engine
    result["active_engine"] = "openai" if result.get("ok") else (
        "deterministic-offline" if settings.allow_offline_engine else "disabled"
    )
    return result
