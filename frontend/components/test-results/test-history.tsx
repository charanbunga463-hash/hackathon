"use client";

/**
 * A project's test history — the answer to "where are my results?".
 *
 * Two lists, because they answer different questions: every run that was
 * executed against this project, and every repair session that resulted from
 * one. Both are fetched per project from endpoints scoped to the owner, and
 * both are loaded only when this tab is opened rather than on every page view.
 */

import { ArrowUpRight, FileText, FlaskConical } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  IconTile,
  Spinner,
} from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useEvents";
import { executionHistory, listSessions } from "@/lib/api";
import { VERDICT_LABEL, VERDICT_TONE, formatDuration, formatRelative } from "@/lib/utils";

export function TestHistory({ projectId }: { projectId: string }) {
  const runs = useAsync(() => executionHistory(projectId), [projectId]);
  const sessions = useAsync(() => listSessions(projectId), [projectId]);

  return (
    <div className="space-y-4">
      <Card className="overflow-hidden">
        <CardHeader
          title="Test runs"
          subtitle="Every run executed against this project"
          icon={
            <IconTile tone="info" size="sm">
              <FlaskConical className="h-3.5 w-3.5" />
            </IconTile>
          }
        />
        {runs.loading && !runs.data ? (
          <Loading label="Loading test history…" />
        ) : runs.error ? (
          <div className="p-4">
            <ErrorNote message={runs.error} />
          </div>
        ) : !runs.data?.length ? (
          <EmptyState
            icon={<FlaskConical className="h-5 w-5" />}
            title="No tests yet"
            description="Run your first API test to see results here."
          />
        ) : (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[32rem] text-sm">
              <thead>
                <tr className="border-b border-line bg-elevated/60 text-left text-2xs font-bold uppercase tracking-wider text-muted">
                  <th scope="col" className="px-4 py-2.5">When</th>
                  <th scope="col" className="px-4 py-2.5">Mode</th>
                  <th scope="col" className="px-4 py-2.5">Result</th>
                  <th scope="col" className="px-4 py-2.5 text-right">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {runs.data.map((run) => (
                  <tr key={run.id} className="transition-colors hover:bg-brand-soft/40">
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-muted">
                      {formatRelative(run.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone="muted">{run.mode}</Badge>
                    </td>
                    <td className="px-4 py-3">
                      <span className="flex flex-wrap items-center gap-2">
                        <Badge tone={run.healthy ? "ok" : "danger"}>
                          {run.healthy ? "Passing" : `${run.failure_count} failing`}
                        </Badge>
                        <span className="truncate text-xs text-muted" title={run.label}>
                          {run.label}
                        </span>
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right text-xs tabular-nums text-muted">
                      {formatDuration(
                        run.test_result?.duration_ms ?? run.api_result?.duration_ms ?? 0,
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="overflow-hidden">
        <CardHeader
          title="Repair sessions"
          subtitle="Each one has a full investigation report"
          icon={
            <IconTile tone="grape" size="sm">
              <FileText className="h-3.5 w-3.5" />
            </IconTile>
          }
        />
        {sessions.loading && !sessions.data ? (
          <Loading label="Loading repair sessions…" />
        ) : sessions.error ? (
          <div className="p-4">
            <ErrorNote message={sessions.error} />
          </div>
        ) : !sessions.data?.length ? (
          <EmptyState
            icon={<FileText className="h-5 w-5" />}
            title="No repairs yet"
            description="Start a repair from a detected failure and its report will appear here."
          />
        ) : (
          <ul className="divide-y divide-line">
            {sessions.data.map((session) => (
              <li
                key={session.id}
                className="flex flex-col gap-2 px-4 py-3.5 transition-colors hover:bg-brand-soft/40 sm:flex-row sm:items-center sm:justify-between"
              >
                <span className="min-w-0">
                  <span className="flex flex-wrap items-center gap-2">
                    <Badge tone={VERDICT_TONE[session.verdict]}>
                      {VERDICT_LABEL[session.verdict]}
                    </Badge>
                    <span className="text-2xs text-faint">
                      {formatRelative(session.created_at)}
                    </span>
                  </span>
                  <span className="mt-1 block truncate text-xs text-muted">{session.summary}</span>
                </span>
                <Link
                  href={`/reports/${session.id}`}
                  className="inline-flex shrink-0 items-center gap-1 self-start rounded-lg border border-brand-line bg-brand-soft px-3 py-1.5 text-xs font-semibold text-brand-ink transition-colors hover:bg-brand-line/50 sm:self-auto"
                >
                  View report
                  <ArrowUpRight className="h-3 w-3" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Loading({ label }: { label: string }) {
  return (
    <p className="flex items-center justify-center gap-2 py-12 text-sm text-muted">
      <Spinner className="h-4 w-4" /> {label}
    </p>
  );
}
