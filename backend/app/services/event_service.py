"""In-process event bus with SSE fan-out.

Subscribers get a bounded queue: a slow browser tab drops events rather than
stalling the repair loop or growing memory without limit. A replay buffer lets a
client that connects mid-run catch up on what it missed.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections import deque
from typing import TYPE_CHECKING, AsyncIterator

from ..models.events import AgentEvent, EventType
from ..utils.logging import get_logger

if TYPE_CHECKING:
    from ..runtime.state import StateBackend

logger = get_logger(__name__)

SUBSCRIBER_QUEUE_SIZE = 512
REPLAY_BUFFER_SIZE = 400


class TooManySubscribers(RuntimeError):
    """Raised when the SSE client cap is reached."""


class EventBus:
    """Fan-out to local SSE clients, and across workers when Redis is configured.

    With several uvicorn workers, a repair running on worker A emits events that
    a browser connected to worker C must still see. Local delivery alone would
    show an empty activity feed for most clients, so every event is also
    published to the shared backend and re-broadcast locally on arrival.
    """

    CHANNEL = "events"

    def __init__(self, state: "StateBackend | None" = None) -> None:
        self._subscribers: set[asyncio.Queue[AgentEvent]] = set()
        self._history: deque[AgentEvent] = deque(maxlen=REPLAY_BUFFER_SIZE)
        self._lock = asyncio.Lock()
        self._state = state
        self._relay: asyncio.Task | None = None
        self._distributed = False
        self._origin = uuid.uuid4().hex[:8]

    async def start(self, state: "StateBackend | None" = None) -> None:
        """Begin relaying events from other workers, if a shared backend exists."""
        from ..runtime.state import MemoryStateBackend, get_state_backend

        self._state = state or self._state or get_state_backend()
        if isinstance(self._state, MemoryStateBackend):
            # Single worker: local fan-out already reaches every client, and a
            # relay would echo every event back to itself.
            self._distributed = False
            return
        self._distributed = True
        self._relay = asyncio.create_task(self._relay_loop(), name="event-relay")

    async def stop(self) -> None:
        if self._relay is not None:
            self._relay.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._relay
            self._relay = None

    async def _relay_loop(self) -> None:
        while True:
            try:
                async for payload in self._state.subscribe(self.CHANNEL):
                    if payload.get("_origin") == self._origin:
                        continue  # our own event; already delivered locally
                    payload.pop("_origin", None)
                    try:
                        event = AgentEvent.model_validate(payload)
                    except Exception:  # noqa: BLE001 - malformed frame must not kill the relay
                        continue
                    await self._deliver_local(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect rather than go silent
                logger.warning("event relay dropped (%s); reconnecting", exc)
                await asyncio.sleep(1.0)

    async def _deliver_local(self, event: AgentEvent) -> None:
        self._history.append(event)
        async with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop the oldest so a stalled client loses history, not liveness.
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    logger.debug("dropping event for a saturated subscriber")

    async def publish(self, event: AgentEvent) -> None:
        # Stamp ownership once, here, rather than at each of the dozens of call
        # sites — a missed one would put another user's file paths and patch
        # text on every open stream.
        if event.tenant is None:
            from ..runtime.middleware import current_tenant

            ambient = current_tenant()
            if ambient and ambient not in {"-", "system"}:
                event.tenant = ambient
        await self._deliver_local(event)
        if self._distributed and self._state is not None:
            payload = event.model_dump(mode="json")
            payload["_origin"] = self._origin
            try:
                await self._state.publish(self.CHANNEL, payload)
            except Exception as exc:  # noqa: BLE001 - local clients still got it
                logger.warning("could not broadcast event to other workers: %s", exc)

    async def subscribe(self, *, max_clients: int | None = None) -> asyncio.Queue[AgentEvent]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        async with self._lock:
            if max_clients is not None and len(self._subscribers) >= max_clients:
                # Each SSE client costs a queue and a task. Refusing the 1001st
                # connection keeps the 1000 already streaming healthy.
                raise TooManySubscribers(
                    f"the event stream is at capacity ({max_clients} clients)"
                )
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[AgentEvent]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    def history(
        self,
        *,
        tenant: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        limit: int = 200,
    ) -> list[AgentEvent]:
        # Owner filtering is not optional: the replay buffer is shared by every
        # connected client, so it holds other tenants' events too.
        events = [e for e in self._history if e.visible_to(tenant)]
        if project_id:
            events = [e for e in events if e.project_id == project_id]
        if session_id:
            events = [e for e in events if e.session_id == session_id]
        return events[-limit:]

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def stream(
        self,
        *,
        tenant: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        replay: bool = True,
        heartbeat_seconds: float = 15.0,
        max_clients: int | None = None,
    ) -> AsyncIterator[str]:
        """SSE generator. Emits a heartbeat so proxies do not close the stream.

        Every client shares one fan-out, so the owner check here is the only
        thing standing between one user's repair log and another user's browser.
        """
        from ..runtime.metrics import get_metrics

        queue = await self.subscribe(max_clients=max_clients)
        metrics = get_metrics()
        metrics.sse_clients.inc(1.0)
        try:
            if replay:
                for event in self.history(
                    tenant=tenant, project_id=project_id, session_id=session_id, limit=100
                ):
                    yield event.to_sse()
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if not event.visible_to(tenant):
                    continue
                if project_id and event.project_id and event.project_id != project_id:
                    continue
                if session_id and event.session_id and event.session_id != session_id:
                    continue
                yield event.to_sse()
        except asyncio.CancelledError:
            raise
        finally:
            metrics.sse_clients.inc(-1.0)
            await self.unsubscribe(queue)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


async def emit(event: AgentEvent) -> None:
    await get_event_bus().publish(event)


async def emit_simple(
    event_type: EventType,
    message: str,
    *,
    project_id: str | None = None,
    **data,
) -> None:
    await emit(AgentEvent(type=event_type, message=message, project_id=project_id, data=data))
