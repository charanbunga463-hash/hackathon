"use client";

import {
  AlertTriangle,
  CheckCircle2,
  FileCode2,
  Quote,
  ShieldQuestion,
  XCircle,
} from "lucide-react";
import * as React from "react";

import { ClaimSection, ClaimTag } from "@/components/ui/claim-ladder";
import { Badge, Progress } from "@/components/ui/primitives";
import { SEVERITY_TONE, cn, percent } from "@/lib/utils";
import type { DiagnosisResult, EvidenceItem, NormalizedFailure } from "@/types";

/**
 * How a failure and its diagnosis are presented everywhere they appear.
 *
 * The layout follows the claim ladder top to bottom — what was measured, then
 * what it means, then how sure we are, then the evidence behind it. Confidence
 * is shown as a number *and* a colour, because "82%" and "we are guessing" are
 * different sentences and the reader deserves both.
 */

export function FailureHeader({ failure }: { failure: NormalizedFailure }) {
  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <ClaimTag kind="observed" />
        <Badge tone={SEVERITY_TONE[failure.severity]}>{failure.severity}</Badge>
        <Badge tone="muted">{failure.source}</Badge>
        {failure.status_code ? (
          <Badge tone={failure.status_code >= 500 ? "danger" : "warn"}>
            HTTP {failure.status_code}
          </Badge>
        ) : null}
      </div>

      <p className="mono break-words text-sm leading-relaxed [overflow-wrap:anywhere]">
        <span className="font-bold text-danger-ink">{failure.error_type}</span>
        {failure.message ? <span className="text-muted">: {failure.message}</span> : null}
      </p>

      {failure.endpoint || failure.test || failure.file ? (
        <div className="flex flex-wrap gap-1.5">
          {failure.endpoint ? <Locator>{failure.endpoint}</Locator> : null}
          {failure.test ? <Locator>{failure.test}</Locator> : null}
          {failure.file ? (
            <Locator>
              {failure.file}
              {failure.line ? `:${failure.line}` : ""}
            </Locator>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function Locator({ children }: { children: React.ReactNode }) {
  return (
    <span className="mono inline-flex max-w-full items-center gap-1 truncate rounded-md border border-line bg-sunken px-2 py-0.5 text-2xs text-muted">
      {children}
    </span>
  );
}

export function EvidenceList({ items }: { items: EvidenceItem[] }) {
  if (!items.length) {
    return (
      <p className="rounded-lg border border-warn-line bg-warn-soft px-3 py-2 text-xs text-warn-ink">
        No evidence was gathered. Without evidence there is no root cause — only a guess.
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {items.map((item, index) => (
        <li key={`${item.source}-${index}`} className="tile p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="flex min-w-0 items-center gap-1.5">
              <FileCode2 className="h-3.5 w-3.5 shrink-0 text-brand" aria-hidden />
              <span className="mono truncate text-xs font-medium text-ink">
                {item.source}
                {item.line ? `:${item.line}` : ""}
              </span>
            </div>
            {item.verified ? (
              <Badge tone="ok">
                <CheckCircle2 className="h-3 w-3" aria-hidden />
                verified
              </Badge>
            ) : (
              <Badge tone="warn">unverified</Badge>
            )}
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-muted">{item.detail}</p>
          {item.excerpt ? (
            <div className="mono mt-2 flex gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-2 text-2xs text-ink">
              <Quote className="mt-0.5 h-3 w-3 shrink-0 text-faint" aria-hidden />
              <code className="whitespace-pre-wrap break-all">{item.excerpt}</code>
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export function DiagnosisPanel({
  diagnosis,
  failure,
  observedFacts,
  className,
}: {
  diagnosis: DiagnosisResult;
  failure?: NormalizedFailure | null;
  observedFacts?: string[];
  className?: string;
}) {
  const confident = diagnosis.confidence >= 0.7;
  const established = diagnosis.confidence > 0;
  const tone = confident ? "ok" : diagnosis.confidence > 0.4 ? "warn" : "danger";

  return (
    <div className={cn("space-y-6", className)}>
      {failure ? <FailureHeader failure={failure} /> : null}

      {observedFacts && observedFacts.length ? (
        <ClaimSection kind="observed" title="What was measured">
          <ul className="space-y-1.5">
            {observedFacts.map((fact, index) => (
              <li key={index} className="mono flex gap-2 text-xs text-muted">
                <span className="text-brand" aria-hidden>
                  ›
                </span>
                <span className="min-w-0 break-words [overflow-wrap:anywhere]">{fact}</span>
              </li>
            ))}
          </ul>
        </ClaimSection>
      ) : null}

      <ClaimSection kind={established ? "root_cause" : "hypothesis"}>
        <p className="text-sm font-medium leading-relaxed text-ink">{diagnosis.root_cause}</p>
        {diagnosis.summary ? (
          <p className="mt-2 text-xs leading-relaxed text-muted">{diagnosis.summary}</p>
        ) : null}
      </ClaimSection>

      {/* -------------------------------------------------------- confidence */}
      <div className="tile space-y-2.5 p-3.5">
        <div className="flex items-center justify-between gap-3">
          <span className="text-2xs font-bold uppercase tracking-wider text-muted">
            Confidence
          </span>
          <span
            className={cn(
              "text-sm font-bold tabular-nums",
              tone === "ok"
                ? "text-ok-ink"
                : tone === "warn"
                  ? "text-warn-ink"
                  : "text-danger-ink",
            )}
          >
            {percent(diagnosis.confidence)}
          </span>
        </div>
        <Progress value={diagnosis.confidence} tone={tone} />
        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          <Badge tone={diagnosis.reasoning_engine === "openai" ? "brand" : "muted"}>
            engine: {diagnosis.reasoning_engine}
          </Badge>
          <Badge tone={diagnosis.grounded ? "ok" : "warn"}>
            {diagnosis.grounded ? "all evidence grounded" : "some evidence dropped"}
          </Badge>
        </div>
      </div>

      {diagnosis.ungrounded_evidence.length ? (
        <div className="rounded-xl border border-warn-line bg-warn-soft p-3.5">
          <p className="flex items-start gap-2 text-xs font-semibold text-warn-ink">
            <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
            {diagnosis.ungrounded_evidence.length} claim(s) could not be verified against the
            workspace and were removed
          </p>
          <ul className="mono mt-2 space-y-1 text-2xs text-warn-ink/85">
            {diagnosis.ungrounded_evidence.map((entry, index) => (
              <li key={index} className="break-words [overflow-wrap:anywhere]">
                {entry}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <section className="space-y-2.5">
        <h3 className="eyebrow text-muted">Evidence</h3>
        <EvidenceList items={diagnosis.evidence} />
      </section>

      {diagnosis.hypotheses.length ? (
        <section className="space-y-2.5">
          <h3 className="eyebrow text-muted">Hypotheses considered</h3>
          <ul className="space-y-2">
            {diagnosis.hypotheses.map((hypothesis, index) => (
              <li key={index} className="tile flex items-start gap-2.5 p-3">
                {hypothesis.status === "supported" ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden />
                ) : hypothesis.status === "rejected" ? (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
                ) : (
                  <ShieldQuestion className="mt-0.5 h-4 w-4 shrink-0 text-warn" aria-hidden />
                )}
                <div className="min-w-0">
                  <p className="text-xs leading-relaxed text-ink">{hypothesis.statement}</p>
                  <p className="mt-0.5 text-2xs font-semibold uppercase tracking-wider text-faint">
                    {hypothesis.status} · {percent(hypothesis.confidence)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {diagnosis.affected_files.length ? (
        <section className="space-y-2.5">
          <h3 className="eyebrow text-muted">Affected files</h3>
          <ul className="space-y-1.5">
            {diagnosis.affected_files.map((file, index) => (
              <li key={index} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
                <span className="mono font-medium text-brand-ink">
                  {file.path}:{file.line_start}
                  {file.line_end !== file.line_start ? `-${file.line_end}` : ""}
                </span>
                <span className="text-muted">{file.reason}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
