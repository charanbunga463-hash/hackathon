"use client";

import {
  BadgeCheck,
  Check,
  CircleDashed,
  Download,
  Loader2,
  Undo2,
  X,
  XCircle,
} from "lucide-react";
import * as React from "react";

import { DiffStats, DiffView } from "@/components/diff-viewer/diff-view";
import { DiagnosisPanel } from "@/components/diagnosis/diagnosis-panel";
import {
  BeforeAfter,
  FailingTestList,
  TestOutput,
  TestRunSummary,
} from "@/components/test-results/test-results";
import { ClaimSection, ClaimTag, VerdictBanner } from "@/components/ui/claim-ladder";
import { Badge, Button, ErrorNote, Panel, PanelHeader } from "@/components/ui/primitives";
import { decidePatch, exportProjectUrl, rollbackSession } from "@/lib/api";
import {
  STAGE_LABEL,
  STAGE_ORDER,
  VERDICT_LABEL,
  VERDICT_TONE,
  cn,
  formatDuration,
  percent,
} from "@/lib/utils";
import type { RepairSession } from "@/types";

const HEADLINE: Record<string, string> = {
  verified: "FIX VERIFIED",
  repair_failed: "REPAIR FAILED",
  patch_applied_unverified: "PATCH APPLIED — NOT VERIFIED",
  awaiting_approval: "AWAITING DEVELOPER APPROVAL",
  rejected_by_developer: "PATCH REJECTED BY DEVELOPER",
  no_failure_detected: "NO FAILURE DETECTED",
  aborted: "STOPPED SAFELY — NO CHANGES APPLIED",
  error: "RUN FAILED",
  pending: "IN PROGRESS",
};

export function StageTrack({ session }: { session: RepairSession }) {
  const currentIndex = STAGE_ORDER.indexOf(session.stage as (typeof STAGE_ORDER)[number]);
  return (
    <ol className="flex flex-wrap items-center gap-1.5">
      {STAGE_ORDER.map((stage, index) => {
        const done = currentIndex > index || session.verdict === "verified";
        const active = currentIndex === index && !session.finished_at;
        return (
          <li key={stage} className="flex items-center gap-1.5">
            <span
              className={cn(
                "flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs",
                done
                  ? "border-ok/30 bg-ok/10 text-ok"
                  : active
                    ? "border-accent/40 bg-accent/10 text-accent"
                    : "border-line bg-elevated text-faint",
              )}
            >
              {done ? (
                <Check className="h-3 w-3" aria-hidden />
              ) : active ? (
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
              ) : (
                <CircleDashed className="h-3 w-3" aria-hidden />
              )}
              {STAGE_LABEL[stage]}
            </span>
            {index < STAGE_ORDER.length - 1 ? (
              <span className="text-faint" aria-hidden>
                ·
              </span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

export function ApprovalGate({
  session,
  onDecided,
}: {
  session: RepairSession;
  onDecided: () => void;
}) {
  const [busy, setBusy] = React.useState<"approve" | "reject" | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const attempt = session.attempts[session.attempts.length - 1];
  const patch = attempt?.patch;
  if (!session.pending_patch_id || !patch) return null;

  const decide = async (approve: boolean) => {
    setBusy(approve ? "approve" : "reject");
    setError(null);
    try {
      await decidePatch(session.project_id, patch.id, approve);
      onDecided();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel className="border-warn/40">
      <PanelHeader
        title="Developer approval required"
        subtitle="Nothing has been written to your files yet."
        icon={<ClaimTag kind="proposed_fix" showIcon={false} />}
      />
      <div className="space-y-3 p-4">
        <div>
          <p className="text-sm font-medium text-ink">{patch.title}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted">{patch.explanation}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="muted">risk: {patch.risk}</Badge>
          <Badge tone="muted">confidence: {percent(patch.confidence)}</Badge>
          <DiffStats diff={patch.diff} />
        </div>
        <DiffView diff={patch.diff} />
        {error ? <ErrorNote message={error} /> : null}
        <div className="flex flex-wrap gap-2">
          <Button
            variant="success"
            size="sm"
            loading={busy === "approve"}
            onClick={() => decide(true)}
          >
            <Check className="h-3.5 w-3.5" /> Apply patch
          </Button>
          <Button
            variant="danger"
            size="sm"
            loading={busy === "reject"}
            onClick={() => decide(false)}
          >
            <X className="h-3.5 w-3.5" /> Reject
          </Button>
        </div>
        <p className="text-2xs leading-relaxed text-muted">
          Approving applies the patch to your workspace, then runs the targeted tests and the
          full suite. A snapshot is taken first, so the change can always be rolled back.
        </p>
      </div>
    </Panel>
  );
}

export function RepairSessionView({
  session,
  running,
  onChanged,
}: {
  session: RepairSession;
  running: boolean;
  onChanged: () => void;
}) {
  const [rollingBack, setRollingBack] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const attempts = session.attempts;
  const last = attempts[attempts.length - 1];
  const applied = attempts.some((a) => a.applied && !a.applied.rolled_back);

  const rollback = async () => {
    setRollingBack(true);
    setError(null);
    try {
      await rollbackSession(session.project_id, session.id);
      onChanged();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRollingBack(false);
    }
  };

  return (
    <div className="space-y-4">
      <VerdictBanner
        verified={session.verdict === "verified"}
        headline={
          running && session.verdict === "pending"
            ? "REPAIR IN PROGRESS"
            : (HEADLINE[session.verdict] ?? VERDICT_LABEL[session.verdict])
        }
        detail={session.summary || undefined}
      />

      <div className="flex flex-wrap items-center gap-2 text-2xs">
        <Badge tone={VERDICT_TONE[session.verdict]}>{VERDICT_LABEL[session.verdict]}</Badge>
        <Badge tone="muted">
          attempt {attempts.length}/{session.max_attempts}
        </Badge>
        <Badge tone={session.reasoning_engine === "openai" ? "accent" : "warn"}>
          {session.reasoning_engine}
        </Badge>
        <Badge tone={session.isolated_execution ? "ok" : "warn"}>
          {session.execution_runner}
          {session.isolated_execution ? " (isolated)" : " (no isolation)"}
        </Badge>
        {session.duration_ms ? (
          <Badge tone="muted">{formatDuration(session.duration_ms)}</Badge>
        ) : null}
      </div>

      <StageTrack session={session} />

      {error ? <ErrorNote message={error} /> : null}

      {session.pending_patch_id ? (
        <ApprovalGate session={session} onDecided={onChanged} />
      ) : null}

      {session.baseline ? (
        <Panel>
          <PanelHeader title="Baseline" subtitle="The state of the project before any change" />
          <div className="space-y-3 p-4">
            <TestRunSummary run={session.baseline} label="Before any patch" />
            <FailingTestList run={session.baseline} />
          </div>
        </Panel>
      ) : null}

      {attempts.map((attempt) => (
        <Panel key={attempt.attempt}>
          <PanelHeader
            title={`Attempt ${attempt.attempt}`}
            subtitle={attempt.failure_reason ?? attempt.outcome}
            actions={
              attempt.verified ? (
                <Badge tone="ok">
                  <BadgeCheck className="h-3 w-3" /> verified
                </Badge>
              ) : attempt.rolled_back ? (
                <Badge tone="warn">
                  <Undo2 className="h-3 w-3" /> rolled back
                </Badge>
              ) : (
                <Badge tone="muted">{attempt.outcome}</Badge>
              )
            }
          />
          <div className="space-y-5 p-4">
            {attempt.investigation ? (
              <details className="rounded-md border border-line">
                <summary className="cursor-pointer px-3 py-2 text-xs text-muted hover:text-ink">
                  Investigation — {attempt.investigation.steps.length} step(s),{" "}
                  {attempt.investigation.files_read.length} file(s) read
                </summary>
                <ol className="space-y-1 border-t border-line p-3">
                  {attempt.investigation.steps.map((step) => (
                    <li key={step.index} className="flex items-start gap-2 text-2xs">
                      <span className="mono w-5 shrink-0 text-right text-faint">
                        {step.index}
                      </span>
                      <span className="mono shrink-0 text-accent">{step.tool}</span>
                      <span className={cn("min-w-0 truncate", step.ok ? "text-muted" : "text-danger")}>
                        {step.result_summary}
                      </span>
                    </li>
                  ))}
                </ol>
                {attempt.investigation.notes.length ? (
                  <p className="border-t border-line px-3 py-2 text-2xs text-faint">
                    {attempt.investigation.notes.join(" ")}
                  </p>
                ) : null}
              </details>
            ) : null}

            {attempt.diagnosis ? (
              <DiagnosisPanel
                diagnosis={attempt.diagnosis}
                failure={session.target_failure}
              />
            ) : null}

            {attempt.patch ? (
              <ClaimSection kind={attempt.verified ? "verified" : "proposed_fix"} title={attempt.patch.title}>
                <p className="text-xs leading-relaxed text-muted">{attempt.patch.explanation}</p>
                <div className="mt-2">
                  <DiffView diff={attempt.patch.diff} />
                </div>
              </ClaimSection>
            ) : null}

            {attempt.validation && !attempt.validation.valid ? (
              <div className="rounded-md border border-danger/30 bg-danger/10 p-3">
                <p className="flex items-center gap-1.5 text-xs font-medium text-danger">
                  <XCircle className="h-3.5 w-3.5" aria-hidden />
                  Patch rejected before it was applied
                </p>
                <ul className="mt-1.5 space-y-1 text-2xs text-danger/90">
                  {attempt.validation.issues.map((issue, index) => (
                    <li key={index}>
                      <span className="mono">[{issue.code}]</span> {issue.message}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {attempt.targeted_test || attempt.full_test ? (
              <div className="space-y-3">
                <BeforeAfter before={session.baseline} after={attempt.full_test} />
                {attempt.targeted_test ? (
                  <TestRunSummary run={attempt.targeted_test} label="Targeted tests" />
                ) : null}
                {attempt.full_test && !attempt.full_test.failures.length ? null : attempt.full_test ? (
                  <FailingTestList run={attempt.full_test} />
                ) : null}
                {attempt.full_test ? <TestOutput run={attempt.full_test} /> : null}
              </div>
            ) : null}

            {attempt.verification ? (
              <div className="rounded-md border border-line bg-canvas p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <ClaimTag kind={attempt.verification.verified ? "verified" : "test_result"} />
                  <Badge tone={attempt.verification.verified ? "ok" : "danger"}>
                    {attempt.verification.verified ? "verified" : "not verified"}
                  </Badge>
                  <Badge tone="muted">source: {attempt.verification.reasoning_engine}</Badge>
                </div>
                <p className="mt-2 text-xs leading-relaxed text-ink">
                  {attempt.verification.verdict_reason}
                </p>
                {attempt.verification.retry_guidance ? (
                  <p className="mt-1.5 text-2xs leading-relaxed text-muted">
                    Next-attempt guidance: {attempt.verification.retry_guidance}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        </Panel>
      ))}

      {applied && !running ? (
        <div className="flex flex-wrap items-center justify-end gap-2">
          <a
            href={exportProjectUrl(session.project_id)}
            download
            className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-xs font-medium h-8 px-3.5 bg-accent text-white hover:bg-accent/90 transition-colors shadow-sm"
          >
            <Download className="h-4 w-4" />
            Export Fixed ZIP
          </a>
          <Button variant="secondary" size="sm" loading={rollingBack} onClick={rollback}>
            <Undo2 className="h-3.5 w-3.5" /> Roll back the applied patch
          </Button>
        </div>
      ) : (
        <div className="flex justify-end">
          <a
            href={exportProjectUrl(session.project_id)}
            download
            className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-xs font-medium h-7 px-2.5 border border-line bg-elevated text-ink hover:bg-line/40 transition-colors"
          >
            <Download className="h-3.5 w-3.5 text-accent" />
            Export Fixed ZIP
          </a>
        </div>
      )}
    </div>
  );
}
