"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { eventStreamUrl } from "@/lib/api";
import type { AgentEvent } from "@/types";

const MAX_EVENTS = 600;

/**
 * Subscribe to the backend's SSE agent-activity stream.
 *
 * The browser's EventSource reconnects on its own, but only for transport
 * errors; we surface the connection state so the UI can say "live" or
 * "disconnected" truthfully rather than silently showing stale data.
 */
export function useEvents(projectId?: string, sessionId?: string) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);
  const seen = useRef<Set<number>>(new Set());

  const clear = useCallback(() => {
    seen.current.clear();
    setEvents([]);
  }, []);

  useEffect(() => {
    const url = eventStreamUrl(projectId, sessionId);
    const source = new EventSource(url);
    sourceRef.current = source;

    const onMessage = (raw: MessageEvent) => {
      try {
        const parsed = JSON.parse(raw.data) as AgentEvent;
        if (seen.current.has(parsed.id)) return;
        seen.current.add(parsed.id);
        setEvents((current) => {
          const next = [...current, parsed];
          return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
        });
      } catch {
        /* a malformed frame must not break the stream */
      }
    };

    // The backend names each event after its type, so a generic listener is
    // registered for every type we know about plus the default channel.
    source.onmessage = onMessage;
    const types = [
      "session.started", "session.finished", "stage.started", "stage.finished",
      "project.created", "project.analyzed", "project.deleted",
      "execution.started", "execution.finished", "failure.detected", "failure.none",
      "agent.thinking", "agent.tool_call", "agent.tool_result", "agent.message",
      "diagnosis.ready", "plan.ready", "patch.proposed", "patch.validated",
      "patch.rejected", "patch.awaiting_approval", "patch.applied", "patch.rolled_back",
      "verification.started", "verification.passed", "verification.failed",
      "retry.scheduled", "warning", "error", "heartbeat",
    ];
    types.forEach((type) => source.addEventListener(type, onMessage as EventListener));

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);

    return () => {
      types.forEach((type) => source.removeEventListener(type, onMessage as EventListener));
      source.close();
      sourceRef.current = null;
      setConnected(false);
    };
  }, [projectId, sessionId]);

  return { events, connected, clear };
}

/** Poll an async function on an interval, with an immediate first call. */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  deps: unknown[] = [],
  enabled = true,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      setData(result);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      await refresh();
    };
    void tick();
    if (intervalMs <= 0) return;
    const timer = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, enabled, ...deps]);

  return { data, error, loading, refresh };
}

/** One-shot async load with a manual refresh. */
export function useAsync<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  return usePolling(fetcher, 0, deps, true);
}
