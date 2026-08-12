"use client";

import {
  BadgeCheck,
  Eye,
  FlaskConical,
  HelpCircle,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * The claim ladder.
 *
 * Every statement the product makes is tagged with what kind of claim it is.
 * This component is the single place that styling lives, so an OBSERVED FACT
 * can never accidentally be rendered with the same weight as a VERIFIED RESULT.
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
  { label: string; icon: React.ElementType; classes: string; blurb: string }
> = {
  observed: {
    label: "OBSERVED FACT",
    icon: Eye,
    classes: "border-info/30 bg-info/10 text-info",
    blurb: "Measured directly from a run or read from a file.",
  },
  hypothesis: {
    label: "HYPOTHESIS",
    icon: HelpCircle,
    classes: "border-warn/30 bg-warn/10 text-warn",
    blurb: "A candidate explanation. Not yet established.",
  },
  root_cause: {
    label: "ROOT CAUSE",
    icon: Wrench,
    classes: "border-accent/30 bg-accent/10 text-accent",
    blurb: "The defect the evidence points to.",
  },
  proposed_fix: {
    label: "PROPOSED FIX",
    icon: Wrench,
    classes: "border-accent/30 bg-accent/10 text-accent",
    blurb: "A change that has not been applied or proven.",
  },
  test_result: {
    label: "TEST RESULT",
    icon: FlaskConical,
    classes: "border-line bg-elevated text-muted",
    blurb: "The raw outcome of running the project's tests.",
  },
  verified: {
    label: "VERIFIED RESULT",
    icon: ShieldCheck,
    classes: "border-ok/40 bg-ok/10 text-ok",
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
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs font-semibold tracking-wide",
        claim.classes,
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
    <section className={cn("space-y-2", className)}>
      <div className="flex items-center gap-2">
        <ClaimTag kind={kind} />
        {title ? <h3 className="text-sm font-semibold text-ink">{title}</h3> : null}
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
        "flex items-start gap-3 rounded-lg border px-4 py-3",
        verified
          ? "border-ok/40 bg-ok/10"
          : "border-warn/40 bg-warn/10",
        className,
      )}
    >
      {verified ? (
        <BadgeCheck className="mt-0.5 h-5 w-5 shrink-0 text-ok" aria-hidden />
      ) : (
        <HelpCircle className="mt-0.5 h-5 w-5 shrink-0 text-warn" aria-hidden />
      )}
      <div className="min-w-0 space-y-1">
        <p
          className={cn(
            "text-sm font-semibold tracking-wide",
            verified ? "text-ok" : "text-warn",
          )}
        >
          {headline}
        </p>
        {detail ? <p className="text-xs leading-relaxed text-muted">{detail}</p> : null}
      </div>
    </div>
  );
}
