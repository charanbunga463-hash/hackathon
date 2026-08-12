"""Real-time agent activity over Server-Sent Events.

Each connected client costs a queue and a streaming task for as long as the tab
is open, so the stream is capped. Refusing the 1001st connection with a clear
503 keeps the 1000 already streaming healthy; accepting it degrades everyone.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ...config.settings import Settings
from ...runtime.identity import Principal
from ...services.event_service import EventBus, TooManySubscribers
from ..deps import current_principal, event_bus, settings_dep

router = APIRouter(prefix="/events", tags=["events"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",   # stop nginx buffering the stream
}


@router.get("")
async def stream_events(
    project_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    replay: bool = Query(default=True),
    principal: Principal = Depends(current_principal),
    bus: EventBus = Depends(event_bus),
    settings: Settings = Depends(settings_dep),
):
    generator = bus.stream(
        tenant=principal.tenant,
        project_id=project_id,
        session_id=session_id,
        replay=replay,
        heartbeat_seconds=settings.sse_heartbeat_seconds,
        max_clients=settings.max_sse_clients,
    )
    try:
        # Pull the first frame here so a capacity refusal becomes a real HTTP
        # error instead of a 200 that immediately closes.
        first = await generator.__anext__()
    except TooManySubscribers as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "10"},
        ) from exc
    except StopAsyncIteration:
        first = ": stream closed\n\n"

    async def body():
        yield first
        async for chunk in generator:
            yield chunk

    return StreamingResponse(body(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/history")
async def event_history(
    project_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    limit: int = Query(default=200, le=400),
    principal: Principal = Depends(current_principal),
    bus: EventBus = Depends(event_bus),
):
    events = bus.history(
        tenant=principal.tenant, project_id=project_id, session_id=session_id, limit=limit
    )
    return {
        "count": len(events),
        "subscribers": bus.subscriber_count,
        "events": [event.model_dump(mode="json", exclude={"tenant"}) for event in events],
    }
