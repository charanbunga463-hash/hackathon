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

import { Badge, EmptyState } from "@/components/ui/primitives";
import { cn, formatTime } from "@/lib/utils";
import type { AgentEvent } from "@/types";

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

const LEVEL_CLASS: Record<string, string> = {
  info: "text-muted",
  success: "text-ok",
  warning: "text-warn",
  error: "text-danger",
  debug: "text-faint",
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
    const atBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight < 60;
    setPinned(atBottom);
  };

  return (
    <div className={cn("flex flex-col min-h-0 h-full overflow-hidden", className)}>
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line px-3.5 py-2.5 bg-surface/50">
        <div className="flex items-center gap-2">
          <Radio
            className={cn("h-3.5 w-3.5", connected ? "text-ok animate-pulse" : "text-faint")}
            aria-hidden
          />
          <span className="text-xs font-medium text-ink">Agent activity</span>
          <Badge tone={connected ? "ok" : "muted"}>
            {connected ? "live" : "disconnected"}
          </Badge>
        </div>
        <span className="text-2xs tabular-nums text-faint">{events.length} events</span>
      </div>

      <div
        onScroll={onScroll}
        className="scroll-thin flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-2 py-2 space-y-1"
      >
        {events.length === 0 ? (
          <EmptyState
            icon={<Radio className="h-6 w-6" />}
            title="No activity yet"
            description={
              emptyHint ??
              "Run tests or start a repair; every step the agent takes streams here in real time."
            }
          />
        ) : (
          <ol className="space-y-1 min-w-0 w-full">
            {events.map((event) => {
              const Icon = ICONS[event.type] ?? CircleDot;
              return (
                <li
                  key={event.id}
                  className="animate-fade-up flex items-start gap-2.5 rounded-md p-2 transition-colors hover:bg-elevated/80 border border-transparent hover:border-line/40 min-w-0 w-full overflow-hidden"
                >
                  <Icon
                    className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", LEVEL_CLASS[event.level])}
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1 overflow-hidden">
                    <p className={cn("text-xs leading-relaxed break-words [overflow-wrap:anywhere] [word-break:break-word]", LEVEL_CLASS[event.level])}>
                      {event.message}
                    </p>
                    <p className="mono mt-1 flex flex-wrap items-center gap-1.5 text-2xs text-faint break-words">
                      <span>{formatTime(event.at)}</span>
                      <span>·</span>
                      <span className="truncate max-w-[140px]">{event.type}</span>
                      {event.attempt ? (
                        <>
                          <span>·</span>
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
          className="shrink-0 border-t border-line px-3 py-1.5 text-2xs text-accent hover:bg-elevated text-center font-medium transition-colors"
        >
          Jump to latest
        </button>
      ) : null}
    </div>
  );
}
