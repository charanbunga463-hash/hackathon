"use client";

import { CheckCircle2, FileSearch, FlaskConical, GitPullRequestArrow } from "lucide-react";

import { cn } from "@/lib/utils";

import { Reveal } from "./motion";

/**
 * The pipeline, laid out as a track rather than a grid.
 *
 * The four stages sit on one connecting line with a light travelling along it,
 * so the eye reads them in pipeline order before it reads a word. Each stage
 * carries its own tone, and those tones are the same ones the app uses for the
 * same concepts — a visitor who signs up meets the colours again with the same
 * meanings.
 */

const STAGES = [
  {
    icon: FlaskConical,
    name: "Detect",
    tone: "info" as const,
    line: "Runs your project's own tests and calls every endpoint it finds.",
    detail: "Real status codes, real response times, real headers. Measured, not guessed.",
  },
  {
    icon: FileSearch,
    name: "Diagnose",
    tone: "brand" as const,
    line: "Reads the actual traceback and the source file it points at.",
    detail:
      "You get the failing file and line number, then a plain-English explanation of the cause.",
  },
  {
    icon: GitPullRequestArrow,
    name: "Repair",
    tone: "grape" as const,
    line: "Proposes the smallest patch that would fix it.",
    detail:
      "You see the exact diff and approve it. Nothing is written to your project without your say-so.",
  },
  {
    icon: CheckCircle2,
    name: "Verify",
    tone: "ok" as const,
    line: "Applies the patch and runs your test suite again.",
    detail: "If the tests do not pass, the change is rolled back and you are told plainly.",
  },
];

const TONE_STYLES = {
  info: { chip: "border-info-line bg-info-soft text-info-ink", dot: "bg-info" },
  brand: { chip: "border-brand-line bg-brand-soft text-brand-ink", dot: "bg-brand" },
  grape: { chip: "border-grape-line bg-grape-soft text-grape-ink", dot: "bg-grape" },
  ok: { chip: "border-ok-line bg-ok-soft text-ok-ink", dot: "bg-ok" },
};

export function Pipeline() {
  return (
    <div className="mt-14">
      {/* The thread the stages hang from. The dash runs along it in pipeline
          order, which is the "time" axis the section is named for. */}
      <div className="relative mb-8 hidden h-px lg:block">
        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-line-strong to-transparent" />
        <svg className="absolute inset-x-0 -top-px h-0.5 w-full overflow-visible" aria-hidden>
          <line
            x1="0"
            y1="1"
            x2="100%"
            y2="1"
            stroke="rgb(var(--brand))"
            strokeWidth="2"
            strokeDasharray="80 160"
            className="animate-dash-flow [filter:drop-shadow(0_0_5px_rgb(var(--brand)/0.6))]"
          />
        </svg>
      </div>

      <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {STAGES.map(({ icon: Icon, name, line, detail, tone }, index) => {
          const style = TONE_STYLES[tone];
          return (
            <Reveal key={name} delay={index * 90}>
              <li className="card card-interactive group relative h-full overflow-hidden p-5">
                {/* The stage number, sunk into the paper. */}
                <span
                  aria-hidden
                  className="mono absolute right-4 top-3 text-4xl font-bold leading-none text-ink/[0.045] transition-colors duration-500 group-hover:text-brand/15"
                >
                  {index + 1}
                </span>

                <span
                  className={cn(
                    "flex h-11 w-11 items-center justify-center rounded-2xl border transition-transform duration-300 group-hover:scale-105",
                    style.chip,
                  )}
                >
                  <Icon className="h-5 w-5" aria-hidden />
                </span>

                <p className="mt-4 flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-[0.14em] text-faint">
                  <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} aria-hidden />
                  Stage {index + 1}
                </p>
                <h3 className="mt-1 text-lg font-bold tracking-tight text-ink">{name}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink/85">{line}</p>
                <p className="mt-2 text-xs leading-relaxed text-muted">{detail}</p>
              </li>
            </Reveal>
          );
        })}
      </ol>
    </div>
  );
}
