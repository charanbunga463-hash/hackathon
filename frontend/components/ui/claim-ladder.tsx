"use client";

import { BadgeCheck, Eye, FlaskConical, HelpCircle, ShieldCheck, Wrench } from "lucide-react";
import * as React from "react";

import type { Tone } from "@/components/ui/primitives";
import { TONE_SOFT } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/**
 * The claim ladder.
 *
 * Every statement the product makes is tagged with what kind of claim it is.
 * This component is the single place that styling lives, so an OBSERVED FACT
 * can never accidentally be rendered with the same weight as a VERIFIED RESULT.
 *
 * The tones climb deliberately: neutral for raw output, blue for something
 * measured, amber for a guess, indigo for a conclusion, green only for a fact
 * proven by a real test run.
 */
export type ClaimKind =
  | "observed"
  | "hypothesis"
  | "root_cause"
  | "proposed_fix"
  | "test_result"
  | "verified";

const CLAIMS: Record<
  ClaimKind,
  { label: string; icon: React.ElementType; tone: Tone; blurb: string }
> = {
  observed: {
    label: "OBSERVED FACT",
    icon: Eye,
    tone: "info",
    blurb: "Measured directly from a run or read from a file.",
  },
  hypothesis: {
    label: "HYPOTHESIS",
    icon: HelpCircle,
    tone: "warn",
    blurb: "A candidate explanation. Not yet established.",
  },
  root_cause: {
    label: "ROOT CAUSE",
    icon: Wrench,
    tone: "brand",
    blurb: "The defect the evidence points to.",
  },
  proposed_fix: {
    label: "PROPOSED FIX",
    icon: Wrench,
    tone: "grape",
    blurb: "A change that has not been applied or proven.",
  },
  test_result: {
    label: "TEST RESULT",
    icon: FlaskConical,
    tone: "muted",
    blurb: "The raw outcome of running the project's tests.",
  },
  verified: {
    label: "VERIFIED RESULT",
    icon: ShieldCheck,
    tone: "ok",
    blurb: "Proven by a real test run after the patch was applied.",
  },
};

export function ClaimTag({
  kind,
  className,
  showIcon = true,
}: {
  kind: ClaimKind;
  className?: string;
  showIcon?: boolean;
}) {
  const claim = CLAIMS[kind];
  const Icon = claim.icon;
  return (
    <span
      title={claim.blurb}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-bold tracking-wide",
        TONE_SOFT[claim.tone],
        className,
      )}
    >
      {showIcon ? <Icon className="h-3 w-3" aria-hidden /> : null}
      {claim.label}
    </span>
  );
}

export function ClaimSection({
  kind,
  title,
  children,
  className,
}: {
  kind: ClaimKind;
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-2.5", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <ClaimTag kind={kind} />
        {title ? <h3 className="text-sm font-bold text-ink">{title}</h3> : null}
      </div>
      <div className="text-sm leading-relaxed text-ink">{children}</div>
    </section>
  );
}

/**
 * The headline verdict. Deliberately the only component that can render the
 * words "FIX VERIFIED", and it requires `verified` to be true to do so.
 */
export function VerdictBanner({
  verified,
  headline,
  detail,
  className,
}: {
  verified: boolean;
  headline: string;
  detail?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative flex items-start gap-3.5 overflow-hidden rounded-card border px-5 py-4 shadow-card",
        verified ? "border-ok-line bg-ok-soft" : "border-warn-line bg-warn-soft",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn("absolute inset-y-0 left-0 w-1", verified ? "bg-ok" : "bg-warn")}
      />
      <span
        className={cn(
          "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl",
          verified ? "bg-ok/15 text-ok-ink" : "bg-warn/15 text-warn-ink",
        )}
      >
        {verified ? (
          <BadgeCheck className="h-5 w-5" aria-hidden />
        ) : (
          <HelpCircle className="h-5 w-5" aria-hidden />
        )}
      </span>
      <div className="min-w-0 space-y-1 pt-0.5">
        <p
          className={cn(
            "text-sm font-bold tracking-wide",
            verified ? "text-ok-ink" : "text-warn-ink",
          )}
        >
          {headline}
        </p>
        {detail ? (
          <p
            className={cn(
              "text-xs leading-relaxed",
              verified ? "text-ok-ink/80" : "text-warn-ink/80",
            )}
          >
            {detail}
          </p>
        ) : null}
      </div>
    </div>
  );
}
