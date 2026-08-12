"use client";

import { FileText } from "lucide-react";

import { DiffView } from "@/components/diff-viewer/diff-view";
import { ClaimSection, ClaimTag } from "@/components/ui/claim-ladder";
import { Badge, Panel, PanelHeader } from "@/components/ui/primitives";
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
    <Panel>
      <PanelHeader title="The investigation" icon={<FileText className="h-4 w-4" />} />
      <div className="space-y-6 p-4">
        <ClaimSection kind="observed" title="What was measured">
          {report.observed_facts.length ? (
            <ul className="space-y-1 text-xs text-muted">
              {report.observed_facts.map((fact, index) => (
                <li key={index} className="mono flex gap-2">
                  <span className="text-faint">•</span>
                  <span>{fact}</span>
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
            <p className="mt-2 text-2xs text-muted">
              Original failure resolved:{" "}
              <strong>{String(report.verification.original_failure_resolved)}</strong> ·
              regressions: <strong>{String(report.verification.regressions_introduced)}</strong>
            </p>
          </ClaimSection>
        ) : null}
      </div>
    </Panel>
  );
}

function EvidenceBlock({ report }: { report: InvestigationReport }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Evidence</h3>
      <ul className="space-y-2">
        {report.evidence.map((item, index) => (
          <li key={index} className="rounded-md border border-line bg-canvas p-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="mono truncate text-xs text-ink">
                {item.source}
                {item.line ? `:${item.line}` : ""}
              </span>
              <Badge tone={item.verified ? "ok" : "warn"}>
                {item.verified ? "verified" : "unverified"}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-muted">{item.detail}</p>
            {item.excerpt ? (
              <pre className="mono mt-1.5 overflow-x-auto rounded border border-line bg-elevated p-2 text-2xs text-ink">
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
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <ClaimTag kind="test_result" />
        <h3 className="text-sm font-semibold text-ink">Test runs</h3>
      </div>
      <div className="scroll-thin overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-line text-left text-2xs uppercase tracking-wide text-faint">
              <th className="py-1.5 pr-2 font-medium">Attempt</th>
              <th className="py-1.5 pr-2 font-medium">Scope</th>
              <th className="py-1.5 pr-2 font-medium">Result</th>
              <th className="py-1.5 text-right font-medium">Exit</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {report.test_results.map((entry, index) => (
              <tr key={index}>
                <td className="py-1.5 pr-2 tabular-nums text-muted">{entry.attempt}</td>
                <td className="py-1.5 pr-2 text-muted">{entry.scope}</td>
                <td className="mono py-1.5 pr-2 text-ink">{entry.summary}</td>
                <td className="py-1.5 text-right">
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
    <Panel className="xl:sticky xl:top-6 xl:self-start">
      <PanelHeader title="Timeline" />
      <ol className="space-y-2 p-4">
        {report.timeline.map((entry, index) => (
          <li key={index} className="flex gap-2.5">
            <div className="flex flex-col items-center">
              <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
              {index < report.timeline.length - 1 ? (
                <span className="h-full w-px flex-1 bg-line" />
              ) : null}
            </div>
            <div className="min-w-0 pb-2">
              <p className="text-2xs uppercase tracking-wide text-faint">
                {formatTime(entry.at)} · {entry.stage}
              </p>
              <p className="text-xs leading-snug text-ink">{entry.detail}</p>
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

/** Provenance chips: which engine reasoned, and whether execution was isolated. */
export function ReportProvenance({ report }: { report: InvestigationReport }) {
  return (
    <div className="flex flex-wrap gap-2 text-2xs">
      <Badge tone="muted">{report.attempts} attempt(s)</Badge>
      <Badge tone={report.reasoning_engine === "openai" ? "accent" : "warn"}>
        engine: {report.reasoning_engine}
      </Badge>
      <Badge tone={report.isolated_execution ? "ok" : "warn"}>
        execution: {report.execution_runner}
        {report.isolated_execution ? " (isolated)" : " (no isolation)"}
      </Badge>
    </div>
  );
}
