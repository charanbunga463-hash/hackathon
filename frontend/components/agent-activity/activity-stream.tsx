"use client";

import {
  AlertTriangle,
  BadgeCheck,
  Bug,
  CircleDot,
  FlaskConical,
  Radio,
  Search,
  Terminal,
  Undo2,
  Wrench,
  XCircle,
} from "lucide-react";
import * as React from "react";

import { EmptyState, StatusDot } from "@/components/ui/primitives";
import { cn, formatTime, type Tone } from "@/lib/utils";
import type { AgentEvent } from "@/types";

/**
 * The live agent feed.
 *
 * Every step the backend takes streams here as it happens. The icon says what
 * kind of step it was; the tone says whether it went well. Both come from the
 * event itself — nothing here decides that a run looks healthy.
 */

const ICONS: Record<string, React.ElementType> = {
  "agent.tool_call": Terminal,
  "agent.tool_result": Search,
  "agent.message": CircleDot,
  "failure.detected": Bug,
  "diagnosis.ready": Search,
  "patch.validated": Wrench,
  "patch.applied": Wrench,
  "patch.rolled_back": Undo2,
  "patch.rejected": XCircle,
  "verification.started": FlaskConical,
  "verification.passed": BadgeCheck,
  "verification.failed": XCircle,
  "retry.scheduled": Undo2,
  warning: AlertTriangle,
  error: XCircle,
};

const LEVEL: Record<string, { tone: Tone; text: string; chip: string }> = {
  info: { tone: "info", text: "text-ink", chip: "border-info-line bg-info-soft text-info-ink" },
  success: { tone: "ok", text: "text-ok-ink", chip: "border-ok-line bg-ok-soft text-ok-ink" },
  warning: {
    tone: "warn",
    text: "text-warn-ink",
    chip: "border-warn-line bg-warn-soft text-warn-ink",
  },
  error: {
    tone: "danger",
    text: "text-danger-ink",
    chip: "border-danger-line bg-danger-soft text-danger-ink",
  },
  debug: { tone: "muted", text: "text-muted", chip: "border-line bg-elevated text-muted" },
};

export function ActivityStream({
  events,
  connected,
  className,
  emptyHint,
}: {
  events: AgentEvent[];
  connected: boolean;
  className?: string;
  emptyHint?: string;
}) {
  const endRef = React.useRef<HTMLDivElement | null>(null);
  const [pinned, setPinned] = React.useState(true);

  React.useEffect(() => {
    if (pinned) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length, pinned]);

  const onScroll = (event: React.UIEvent<HTMLDivElement>) => {
    const element = event.currentTarget;
    const atBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 60;
    setPinned(atBottom);
  };

  return (
    <div className={cn("flex h-full min-h-0 flex-col overflow-hidden", className)}>
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line bg-elevated/60 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <StatusDot tone={connected ? "ok" : "muted"} pulse={connected} />
          <span className="truncate text-xs font-bold text-ink">Agent activity</span>
          <span
            className={cn(
              "rounded-full border px-2 py-0.5 text-2xs font-semibold",
              connected
                ? "border-ok-line bg-ok-soft text-ok-ink"
                : "border-line bg-elevated text-muted",
            )}
          >
            {connected ? "live" : "offline"}
          </span>
        </div>
        <span className="shrink-0 text-2xs font-medium tabular-nums text-faint">
          {events.length} events
        </span>
      </div>

      <div
        onScroll={onScroll}
        className="scroll-thin min-h-0 flex-1 space-y-1 overflow-y-auto overflow-x-hidden p-2"
      >
        {events.length === 0 ? (
          <EmptyState
            icon={<Radio className="h-5 w-5" />}
            title="No activity yet"
            description={
              emptyHint ??
              "Run tests or start a repair; every step the agent takes streams here in real time."
            }
          />
        ) : (
          <ol className="w-full min-w-0 space-y-1">
            {events.map((event) => {
              const Icon = ICONS[event.type] ?? CircleDot;
              const level = LEVEL[event.level] ?? LEVEL.info;
              return (
                <li
                  key={event.id}
                  className="flex w-full min-w-0 animate-fade-up items-start gap-2.5 rounded-xl border border-transparent p-2.5 transition-colors hover:border-line hover:bg-elevated/70"
                >
                  <span
                    className={cn(
                      "mt-px flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border",
                      level.chip,
                    )}
                    aria-hidden
                  >
                    <Icon className="h-3 w-3" />
                  </span>
                  <div className="min-w-0 flex-1 overflow-hidden">
                    <p
                      className={cn(
                        "break-words text-xs leading-relaxed [overflow-wrap:anywhere]",
                        level.text,
                      )}
                    >
                      {event.message}
                    </p>
                    <p className="mono mt-1 flex flex-wrap items-center gap-1.5 text-2xs text-faint">
                      <span className="tabular-nums">{formatTime(event.at)}</span>
                      <span aria-hidden>·</span>
                      <span className="max-w-[9rem] truncate">{event.type}</span>
                      {event.attempt ? (
                        <>
                          <span aria-hidden>·</span>
                          <span>attempt {event.attempt}</span>
                        </>
                      ) : null}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
        <div ref={endRef} />
      </div>

      {!pinned ? (
        <button
          onClick={() => setPinned(true)}
          className="shrink-0 border-t border-line bg-brand-soft px-3 py-2 text-center text-2xs font-semibold text-brand-ink transition-colors hover:bg-brand-line/50"
        >
          Jump to latest
        </button>
      ) : null}
    </div>
  );
}
