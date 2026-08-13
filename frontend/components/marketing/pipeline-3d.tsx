"use client";

import { useState } from "react";
import {
  CheckCircle2,
  FileSearch,
  FlaskConical,
  GitPullRequestArrow,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { Reveal } from "./motion";

/**
 * The pipeline, staged in depth.
 *
 * The four cards fan away from the viewer in Z, so the eye reads them in
 * pipeline order before it reads a word. Hovering one brings it forward and
 * squares it to the camera — the stage you are considering is the one in
 * focus, and the others stay legible behind it.
 *
 * The stage copy is the same set of claims the product makes elsewhere; the
 * presentation changed, the promises did not.
 */

const STAGES = [
  {
    icon: FlaskConical,
    name: "Detect",
    line: "Runs your project's own tests and calls every endpoint it finds.",
    detail:
      "Real status codes, real response times, real headers. Measured, not guessed.",
  },
  {
    icon: FileSearch,
    name: "Diagnose",
    line: "Reads the actual traceback and the source file it points at.",
    detail:
      "You get the failing file and line number, then a plain-English explanation of the cause.",
  },
  {
    icon: GitPullRequestArrow,
    name: "Repair",
    line: "Proposes the smallest patch that would fix it.",
    detail:
      "You see the exact diff and approve it. Nothing is written to your project without your say-so.",
  },
  {
    icon: CheckCircle2,
    name: "Verify",
    line: "Applies the patch and runs your test suite again.",
    detail:
      "If the tests do not pass, the change is rolled back and you are told plainly.",
  },
];

export function Pipeline3D() {
  const [active, setActive] = useState<number | null>(null);

  return (
    <div className="scene mt-12">
      {/* The thread the stages hang from. The dash animation runs along it in
          pipeline order, which is the "time" axis the section is named for. */}
      <div className="relative mb-7 hidden h-px md:block">
        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-line to-transparent" />
        <svg
          className="absolute inset-x-0 -top-px h-0.5 w-full overflow-visible"
          aria-hidden
        >
          <line
            x1="0"
            y1="1"
            x2="100%"
            y2="1"
            stroke="rgb(var(--accent))"
            strokeWidth="1.5"
            strokeDasharray="90 130"
            className="animate-trace-dash [filter:drop-shadow(0_0_6px_rgb(var(--accent)/0.9))]"
          />
        </svg>
      </div>

      <ol
        className="depth grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
        onMouseLeave={() => setActive(null)}
      >
        {STAGES.map(({ icon: Icon, name, line, detail }, index) => {
          const isActive = active === index;
          const dimmed = active !== null && !isActive;

          return (
            <Reveal key={name} delay={index * 90}>
              <li
                onMouseEnter={() => setActive(index)}
                onFocus={() => setActive(index)}
                className={cn(
                  "depth glass edge-lit group relative h-full rounded-xl p-5",
                  "transition-[transform,opacity,box-shadow] duration-500 ease-out",
                  "motion-reduce:!transform-none",
                  dimmed && "opacity-60",
                )}
                style={{
                  // Each card starts further back and more angled than the last,
                  // then comes square to the camera on hover.
                  transform: isActive
                    ? "translateZ(60px) rotateY(0deg) translateY(-6px)"
                    : `translateZ(${-index * 22}px) rotateY(${-index * 4 + 6}deg)`,
                }}
                tabIndex={0}
              >
                {/* Stage number, sunk slightly behind the card face. */}
                <span
                  aria-hidden
                  className="absolute right-4 top-3 mono text-4xl font-bold leading-none text-ink/[0.055] transition-colors duration-500 group-hover:text-accent/15"
                >
                  {index + 1}
                </span>

                <span
                  className={cn(
                    "relative flex h-10 w-10 items-center justify-center rounded-lg",
                    "bg-accent/10 text-accent transition-all duration-500",
                    "group-hover:bg-accent/20 group-hover:shadow-[0_0_28px_-4px_rgb(var(--accent)/0.65)]",
                  )}
                  style={{ transform: "translateZ(28px)" }}
                >
                  <Icon className="h-5 w-5" aria-hidden />
                </span>

                <div style={{ transform: "translateZ(16px)" }}>
                  <span className="mt-4 block text-2xs font-medium uppercase tracking-wider text-faint">
                    Stage {index + 1}
                  </span>
                  <h3 className="mt-1 text-base font-semibold tracking-tight text-ink">
                    {name}
                  </h3>
                  <p className="mt-2.5 text-sm leading-relaxed text-ink/90">
                    {line}
                  </p>
                  <p className="mt-2 text-xs leading-relaxed text-muted">
                    {detail}
                  </p>
                </div>
              </li>
            </Reveal>
          );
        })}
      </ol>
    </div>
  );
}
