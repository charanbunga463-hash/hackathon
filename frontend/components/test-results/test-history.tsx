"use client";

/**
 * A project's test history — the answer to "where are my results?".
 *
 * Two lists, because they answer different questions: every run that was
 * executed against this project, and every repair session that resulted from
 * one. Both are fetched per project from endpoints scoped to the owner, and
 * both are loaded only when this tab is opened rather than on every page view.
 */

import { FileText, FlaskConical } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import {
  Badge,
  EmptyState,
  ErrorNote,
  Panel,
  PanelHeader,
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
      <Panel>
        <PanelHeader
          title="Test runs"
          subtitle="Every run executed against this project"
          icon={<FlaskConical className="h-4 w-4" />}
        />
        {runs.loading && !runs.data ? (
          <Loading label="Loading test history…" />
        ) : runs.error ? (
          <div className="p-4">
            <ErrorNote message={runs.error} />
          </div>
        ) : !runs.data?.length ? (
          <EmptyState
            icon={<FlaskConical className="h-7 w-7" />}
            title="No tests yet"
            description="Run your first API test to see results here."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-faint">
                  <th scope="col" className="px-4 py-2.5 font-medium">When</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Mode</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Result</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">Duration</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((run) => (
                  <tr key={run.id} className="border-b border-line last:border-0">
                    <td className="whitespace-nowrap px-4 py-2.5 text-muted">
                      {formatRelative(run.created_at)}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge tone="muted">{run.mode}</Badge>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="flex flex-wrap items-center gap-2">
                        <Badge tone={run.healthy ? "ok" : "danger"}>
                          {run.healthy ? "Passing" : `${run.failure_count} failing`}
                        </Badge>
                        <span className="truncate text-xs text-muted" title={run.label}>
                          {run.label}
                        </span>
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-right tabular-nums text-muted">
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
      </Panel>

      <Panel>
        <PanelHeader
          title="Repair sessions"
          subtitle="Each one has a full investigation report"
          icon={<FileText className="h-4 w-4" />}
        />
        {sessions.loading && !sessions.data ? (
          <Loading label="Loading repair sessions…" />
        ) : sessions.error ? (
          <div className="p-4">
            <ErrorNote message={sessions.error} />
          </div>
        ) : !sessions.data?.length ? (
          <EmptyState
            icon={<FileText className="h-7 w-7" />}
            title="No repairs yet"
            description="Start a repair from a detected failure and its report will appear here."
          />
        ) : (
          <ul className="divide-y divide-line">
            {sessions.data.map((session) => (
              <li
                key={session.id}
                className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <span className="min-w-0">
                  <span className="flex flex-wrap items-center gap-2">
                    <Badge tone={VERDICT_TONE[session.verdict]}>
                      {VERDICT_LABEL[session.verdict]}
                    </Badge>
                    <span className="text-xs text-faint">
                      {formatRelative(session.created_at)}
                    </span>
                  </span>
                  <span className="mt-1 block truncate text-xs text-muted">
                    {session.summary}
                  </span>
                </span>
                <Link
                  href={`/reports/${session.id}`}
                  className="shrink-0 rounded-md px-2.5 py-1 text-xs font-medium text-accent hover:bg-accent/10"
                >
                  View report
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

function Loading({ label }: { label: string }) {
  return (
    <p className="flex items-center justify-center gap-2 py-10 text-sm text-muted">
      <Spinner className="h-4 w-4" /> {label}
    </p>
  );
}
