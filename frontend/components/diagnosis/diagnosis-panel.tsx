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

export function FailureHeader({ failure }: { failure: NormalizedFailure }) {
  return (
    <div className="space-y-2">
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
      <p className="mono text-sm text-ink">
        <span className="text-danger">{failure.error_type}</span>
        {failure.message ? <span className="text-muted">: {failure.message}</span> : null}
      </p>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {failure.endpoint ? (
          <span className="mono">{failure.endpoint}</span>
        ) : null}
        {failure.test ? <span className="mono">{failure.test}</span> : null}
        {failure.file ? (
          <span className="mono">
            {failure.file}
            {failure.line ? `:${failure.line}` : ""}
          </span>
        ) : null}
      </div>
    </div>
  );
}

export function EvidenceList({ items }: { items: EvidenceItem[] }) {
  if (!items.length) {
    return (
      <p className="text-xs text-muted">
        No evidence was gathered. Without evidence there is no root cause — only a guess.
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {items.map((item, index) => (
        <li key={`${item.source}-${index}`} className="rounded-md border border-line bg-canvas p-2.5">
          <div className="flex items-start justify-between gap-2">
            <div className="flex min-w-0 items-center gap-1.5">
              <FileCode2 className="h-3.5 w-3.5 shrink-0 text-faint" aria-hidden />
              <span className="mono truncate text-xs text-ink">
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
            <div className="mono mt-2 flex gap-1.5 rounded border border-line bg-elevated px-2 py-1.5 text-2xs text-ink">
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

  return (
    <div className={cn("space-y-5", className)}>
      {failure ? <FailureHeader failure={failure} /> : null}

      {observedFacts && observedFacts.length ? (
        <ClaimSection kind="observed" title="What was measured">
          <ul className="space-y-1 text-xs text-muted">
            {observedFacts.map((fact, index) => (
              <li key={index} className="flex gap-2">
                <span className="text-faint">•</span>
                <span className="mono">{fact}</span>
              </li>
            ))}
          </ul>
        </ClaimSection>
      ) : null}

      <ClaimSection kind={established ? "root_cause" : "hypothesis"}>
        <p className="text-sm leading-relaxed">{diagnosis.root_cause}</p>
        {diagnosis.summary ? (
          <p className="mt-2 text-xs leading-relaxed text-muted">{diagnosis.summary}</p>
        ) : null}
      </ClaimSection>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-medium text-muted">Confidence</span>
          <span
            className={cn(
              "text-xs font-semibold tabular-nums",
              confident ? "text-ok" : diagnosis.confidence > 0.4 ? "text-warn" : "text-danger",
            )}
          >
            {percent(diagnosis.confidence)}
          </span>
        </div>
        <Progress
          value={diagnosis.confidence}
          tone={confident ? "ok" : diagnosis.confidence > 0.4 ? "accent" : "danger"}
        />
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Badge tone={diagnosis.reasoning_engine === "openai" ? "accent" : "muted"}>
            engine: {diagnosis.reasoning_engine}
          </Badge>
          <Badge tone={diagnosis.grounded ? "ok" : "warn"}>
            {diagnosis.grounded ? "all evidence grounded" : "some evidence dropped"}
          </Badge>
        </div>
      </div>

      {diagnosis.ungrounded_evidence.length ? (
        <div className="rounded-md border border-warn/30 bg-warn/10 p-3">
          <p className="flex items-center gap-1.5 text-xs font-medium text-warn">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
            {diagnosis.ungrounded_evidence.length} claim(s) could not be verified against the
            workspace and were removed
          </p>
          <ul className="mono mt-1.5 space-y-0.5 text-2xs text-warn/90">
            {diagnosis.ungrounded_evidence.map((entry, index) => (
              <li key={index}>{entry}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Evidence</h3>
        <EvidenceList items={diagnosis.evidence} />
      </section>

      {diagnosis.hypotheses.length ? (
        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Hypotheses considered
          </h3>
          <ul className="space-y-1.5">
            {diagnosis.hypotheses.map((hypothesis, index) => (
              <li
                key={index}
                className="flex items-start gap-2 rounded-md border border-line bg-canvas p-2.5"
              >
                {hypothesis.status === "supported" ? (
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok" aria-hidden />
                ) : hypothesis.status === "rejected" ? (
                  <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" aria-hidden />
                ) : (
                  <ShieldQuestion className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" aria-hidden />
                )}
                <div className="min-w-0">
                  <p className="text-xs text-ink">{hypothesis.statement}</p>
                  <p className="text-2xs uppercase tracking-wide text-faint">
                    {hypothesis.status} · {percent(hypothesis.confidence)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {diagnosis.affected_files.length ? (
        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Affected files
          </h3>
          <ul className="space-y-1">
            {diagnosis.affected_files.map((file, index) => (
              <li key={index} className="flex items-baseline gap-2 text-xs">
                <span className="mono text-ink">
                  {file.path}:{file.line_start}
                  {file.line_end !== file.line_start ? `-${file.line_end}` : ""}
                </span>
                <span className="truncate text-muted">{file.reason}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
