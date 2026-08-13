"use client";

import { FileText } from "lucide-react";

import { DiffView } from "@/components/diff-viewer/diff-view";
import { ClaimSection, ClaimTag } from "@/components/ui/claim-ladder";
import { Badge, Card, CardHeader, IconTile } from "@/components/ui/primitives";
import { formatTime } from "@/lib/utils";
import type { InvestigationReport } from "@/types";

/**
 * The investigation report body.
 *
 * Laid out strictly as the claim ladder — observed facts, hypotheses, root
 * cause, evidence, fix, test results, verdict — so a reader can always tell
 * which rung a statement sits on. The verdict section reuses `ClaimSection`
 * with `verified` only when the report says the run actually passed.
 */
export function InvestigationReportBody({ report }: { report: InvestigationReport }) {
  return (
    <Card>
      <CardHeader
        title="The investigation"
        icon={
          <IconTile tone="brand" size="sm">
            <FileText className="h-3.5 w-3.5" />
          </IconTile>
        }
      />
      <div className="space-y-7 p-4 sm:p-5">
        <ClaimSection kind="observed" title="What was measured">
          {report.observed_facts.length ? (
            <ul className="space-y-1.5">
              {report.observed_facts.map((fact, index) => (
                <li key={index} className="mono flex gap-2 text-xs text-muted">
                  <span className="text-brand" aria-hidden>
                    ›
                  </span>
                  <span className="min-w-0 break-words [overflow-wrap:anywhere]">{fact}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted">No observations recorded.</p>
          )}
        </ClaimSection>

        {report.hypotheses.length ? (
          <ClaimSection kind="hypothesis" title="Alternatives considered">
            <ul className="space-y-1 text-xs text-muted">
              {report.hypotheses.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </ClaimSection>
        ) : null}

        <ClaimSection kind="root_cause" title="Root cause">
          <p className="text-sm leading-relaxed">{report.root_cause ?? "Not established."}</p>
        </ClaimSection>

        {report.evidence.length ? <EvidenceBlock report={report} /> : null}

        {report.proposed_fix ? (
          <ClaimSection kind={report.verified ? "verified" : "proposed_fix"} title="The fix">
            <p className="text-xs leading-relaxed text-muted">{report.proposed_fix}</p>
          </ClaimSection>
        ) : null}

        {report.diff ? <DiffView diff={report.diff} /> : null}

        {report.test_results.length ? <TestResultsTable report={report} /> : null}

        {report.verification ? (
          <ClaimSection kind={report.verified ? "verified" : "test_result"} title="Verdict">
            <p className="text-sm leading-relaxed">{report.verification.verdict_reason}</p>
            <p className="mt-2 flex flex-wrap gap-2">
              <Badge tone={report.verification.original_failure_resolved ? "ok" : "danger"}>
                original failure{" "}
                {report.verification.original_failure_resolved ? "resolved" : "not resolved"}
              </Badge>
              <Badge tone={report.verification.regressions_introduced ? "danger" : "ok"}>
                {report.verification.regressions_introduced
                  ? "regressions introduced"
                  : "no regressions"}
              </Badge>
            </p>
          </ClaimSection>
        ) : null}
      </div>
    </Card>
  );
}

function EvidenceBlock({ report }: { report: InvestigationReport }) {
  return (
    <section className="space-y-2.5">
      <h3 className="eyebrow text-muted">Evidence</h3>
      <ul className="space-y-2">
        {report.evidence.map((item, index) => (
          <li key={index} className="tile p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="mono truncate text-xs font-medium text-ink">
                {item.source}
                {item.line ? `:${item.line}` : ""}
              </span>
              <Badge tone={item.verified ? "ok" : "warn"}>
                {item.verified ? "verified" : "unverified"}
              </Badge>
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-muted">{item.detail}</p>
            {item.excerpt ? (
              <pre className="mono scroll-thin mt-2 overflow-x-auto rounded-lg border border-line bg-surface p-2.5 text-2xs text-ink">
                {item.excerpt}
              </pre>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function TestResultsTable({ report }: { report: InvestigationReport }) {
  return (
    <section className="space-y-2.5">
      <div className="flex items-center gap-2">
        <ClaimTag kind="test_result" />
        <h3 className="text-sm font-bold text-ink">Test runs</h3>
      </div>
      <div className="scroll-thin overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-line bg-elevated/60 text-left text-2xs font-bold uppercase tracking-wider text-muted">
              <th className="px-3 py-2">Attempt</th>
              <th className="px-3 py-2">Scope</th>
              <th className="px-3 py-2">Result</th>
              <th className="px-3 py-2 text-right">Exit</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {report.test_results.map((entry, index) => (
              <tr key={index}>
                <td className="px-3 py-2 tabular-nums text-muted">{entry.attempt}</td>
                <td className="px-3 py-2 text-muted">{entry.scope}</td>
                <td className="mono px-3 py-2 text-ink">{entry.summary}</td>
                <td className="px-3 py-2 text-right">
                  <Badge tone={entry.exit_code === 0 ? "ok" : "danger"}>{entry.exit_code}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** Chronological trace of the run, for auditing what happened when. */
export function ReportTimeline({ report }: { report: InvestigationReport }) {
  return (
    <Card className="xl:sticky xl:top-20 xl:self-start">
      <CardHeader title="Timeline" />
      <ol className="p-4">
        {report.timeline.map((entry, index) => (
          <li key={index} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-brand ring-4 ring-brand-soft" />
              {index < report.timeline.length - 1 ? (
                <span className="h-full w-px flex-1 bg-line" />
              ) : null}
            </div>
            <div className="min-w-0 pb-4">
              <p className="text-2xs font-semibold uppercase tracking-wider text-faint">
                {formatTime(entry.at)} · {entry.stage}
              </p>
              <p className="mt-0.5 text-xs leading-relaxed text-ink">{entry.detail}</p>
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/** Provenance chips: which engine reasoned, and whether execution was isolated. */
export function ReportProvenance({ report }: { report: InvestigationReport }) {
  return (
    <div className="flex flex-wrap gap-2">
      <Badge tone="muted">{report.attempts} attempt(s)</Badge>
      <Badge tone={report.reasoning_engine === "openai" ? "brand" : "warn"}>
        engine: {report.reasoning_engine}
      </Badge>
      <Badge tone={report.isolated_execution ? "ok" : "warn"}>
        execution: {report.execution_runner}
        {report.isolated_execution ? " (isolated)" : " (no isolation)"}
      </Badge>
    </div>
  );
}
