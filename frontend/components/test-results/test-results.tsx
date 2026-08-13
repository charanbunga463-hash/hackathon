"use client";

import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleSlash,
  Clock,
  XCircle,
} from "lucide-react";
import * as React from "react";

import { ClaimTag } from "@/components/ui/claim-ladder";
import { Badge, Progress } from "@/components/ui/primitives";
import { cn, formatDuration } from "@/lib/utils";
import type { TestRunResult } from "@/types";

/**
 * How a test run is reported.
 *
 * The verdict comes from the exit code, never from a count we computed — a
 * suite can report zero failures and still exit non-zero, and that is a red
 * run. The bar underneath is pass ratio, so a mostly-green run with one
 * failure still reads as failing.
 */

export function TestRunSummary({
  run,
  label,
  className,
}: {
  run: TestRunResult;
  label?: string;
  className?: string;
}) {
  const failed = run.failed + run.errors;
  const ratio = run.total > 0 ? run.passed / run.total : 0;
  const green = run.exit_code === 0 && failed === 0 && !run.timed_out;

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <ClaimTag kind="test_result" />
        {label ? <span className="text-xs font-semibold text-ink">{label}</span> : null}
        <Badge tone={green ? "ok" : "danger"}>
          {green ? (
            <CheckCircle2 className="h-3 w-3" aria-hidden />
          ) : (
            <XCircle className="h-3 w-3" aria-hidden />
          )}
          exit {run.exit_code}
        </Badge>
        {run.timed_out ? <Badge tone="danger">timed out</Badge> : null}
        <Badge tone="muted">
          <Clock className="h-3 w-3" aria-hidden />
          {formatDuration(run.duration_ms)}
        </Badge>
        <Badge tone="muted">{run.runner}</Badge>
      </div>

      <Progress value={ratio} tone={green ? "ok" : "danger"} />

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs font-medium tabular-nums">
        <span className="text-ok-ink">{run.passed} passed</span>
        <span className={failed ? "text-danger-ink" : "text-muted"}>{failed} failed</span>
        {run.skipped ? <span className="text-muted">{run.skipped} skipped</span> : null}
        <span className="text-muted">{run.total} total</span>
      </div>

      {run.collection_error ? (
        <pre className="mono scroll-thin max-h-32 overflow-auto whitespace-pre-wrap rounded-lg border border-danger-line bg-danger-soft p-2.5 text-2xs text-danger-ink">
          {run.collection_error}
        </pre>
      ) : null}
    </div>
  );
}

export function FailingTestList({ run }: { run: TestRunResult }) {
  const failing = run.cases.filter((c) => c.outcome === "failed" || c.outcome === "error");
  if (!failing.length) return null;
  return (
    <ul className="space-y-1.5">
      {failing.map((testCase) => (
        <li
          key={testCase.node_id}
          className="flex items-start gap-2 rounded-lg border border-danger-line bg-danger-soft px-3 py-2"
        >
          <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" aria-hidden />
          <div className="min-w-0">
            <p className="mono truncate text-xs font-semibold text-ink">{testCase.node_id}</p>
            {testCase.message ? (
              <p className="mono truncate text-2xs text-danger-ink/85">{testCase.message}</p>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** The raw pytest output, collapsed by default because it is long and loud. */
export function TestOutput({ run }: { run: TestRunResult }) {
  const [open, setOpen] = React.useState(false);
  const text = [run.stdout, run.stderr].filter(Boolean).join("\n");
  if (!text.trim()) return null;

  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <button
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-1.5 bg-elevated/60 px-3 py-2.5 text-left text-xs font-semibold text-muted transition-colors hover:bg-elevated hover:text-ink"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" aria-hidden />
        )}
        Raw pytest output
      </button>
      {open ? (
        <pre className="mono scroll-thin max-h-96 overflow-auto whitespace-pre-wrap border-t border-line bg-sunken p-3.5 text-2xs leading-relaxed text-muted">
          {text}
        </pre>
      ) : null}
    </div>
  );
}

/** The two runs side by side. The whole product is the difference between them. */
export function BeforeAfter({
  before,
  after,
}: {
  before?: TestRunResult | null;
  after?: TestRunResult | null;
}) {
  if (!before && !after) return null;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="rounded-xl border border-line bg-sunken p-3.5">
        <p className="mb-2.5 text-2xs font-bold uppercase tracking-wider text-muted">
          Before the patch
        </p>
        {before ? (
          <TestRunSummary run={before} />
        ) : (
          <p className="flex items-center gap-1.5 text-xs text-muted">
            <CircleSlash className="h-3.5 w-3.5" aria-hidden /> no baseline recorded
          </p>
        )}
      </div>
      <div className="rounded-xl border border-brand-line bg-brand-soft/50 p-3.5">
        <p className="mb-2.5 text-2xs font-bold uppercase tracking-wider text-brand-ink">
          After the patch
        </p>
        {after ? (
          <TestRunSummary run={after} />
        ) : (
          <p className="flex items-center gap-1.5 text-xs text-muted">
            <CircleSlash className="h-3.5 w-3.5" aria-hidden /> not run
          </p>
        )}
      </div>
    </div>
  );
}
