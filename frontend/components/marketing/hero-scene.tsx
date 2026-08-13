"use client";

import { CheckCircle2, CircleAlert, FileCode2, Sparkles } from "lucide-react";

/**
 * The hero object: one real repair, told in three surfaces.
 *
 * A failing test run, the patch the agent proposed, and the verdict after the
 * suite was run again. The content is a genuine walk-through of the product's
 * own output, so the prettiest thing on the page is also the most honest one.
 *
 * Pure CSS and pure light: white cards, tinted status washes, and two small
 * floating chips. No dark chrome anywhere — a "terminal" panel would be the
 * one dark rectangle on an otherwise bright page.
 */
export function HeroScene() {
  return (
    <div className="relative mx-auto w-full max-w-lg">
      {/* The glow the stack sits in. */}
      <div
        aria-hidden
        className="absolute -inset-6 rounded-[2.5rem] bg-[radial-gradient(60%_60%_at_50%_40%,rgb(var(--brand)/0.16),transparent_70%)] blur-2xl"
      />

      <div className="relative space-y-3">
        {/* ------------------------------------------------- the test run -- */}
        <div className="card overflow-hidden shadow-raised">
          <div className="flex items-center gap-2 border-b border-line bg-elevated/70 px-4 py-2.5">
            <FileCode2 className="h-3.5 w-3.5 text-brand" aria-hidden />
            <span className="mono text-2xs font-medium text-muted">
              tests/test_orders.py
            </span>
            <span className="ml-auto flex items-center gap-1 rounded-full border border-danger-line bg-danger-soft px-2 py-0.5 text-2xs font-semibold text-danger-ink">
              <CircleAlert className="h-3 w-3" aria-hidden />1 failed
            </span>
          </div>

          <ul className="mono divide-y divide-line/70 text-2xs">
            <TestRow name="test_list_orders" state="pass" />
            <TestRow name="test_create_order" state="pass" />
            <TestRow name="test_order_total" state="fail" />
            <TestRow name="test_cancel_order" state="pass" />
          </ul>

          <div className="border-t border-line bg-danger-soft/60 px-4 py-2.5">
            <p className="mono text-2xs leading-relaxed text-danger-ink">
              <span className="text-muted">app/services/orders.py:47</span>
              <br />
              TypeError: unsupported operand &apos;NoneType&apos; and &apos;int&apos;
            </p>
          </div>
        </div>

        {/* ---------------------------------------------------- the patch -- */}
        <div className="card overflow-hidden shadow-raised">
          <div className="flex items-center justify-between border-b border-line bg-elevated/70 px-4 py-2.5">
            <span className="flex items-center gap-2 text-2xs font-semibold text-brand-ink">
              <Sparkles className="h-3.5 w-3.5 text-brand" aria-hidden />
              Proposed patch
            </span>
            <span className="mono text-2xs text-faint">+1 −1</span>
          </div>
          <div className="mono space-y-px py-2 text-2xs leading-relaxed">
            <div className="diff-line-del px-4">
              <span className="text-faint">− </span>
              total += item.price * qty
            </div>
            <div className="diff-line-add px-4">
              <span className="text-faint">+ </span>
              total += (item.price or 0) * qty
            </div>
          </div>
        </div>

        {/* -------------------------------------------------- the verdict -- */}
        <div className="flex items-center gap-3 rounded-card border border-ok-line bg-ok-soft px-4 py-3 shadow-raised">
          <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-ok/15 text-ok-ink">
            <span className="absolute inset-0 animate-ping rounded-xl bg-ok/15 [animation-duration:2.6s]" />
            <CheckCircle2 className="relative h-4.5 w-4.5" aria-hidden />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-bold text-ok-ink">Fix verified</p>
            <p className="mono text-2xs text-ok-ink/80">
              4 passed · 0 failed · exit 0
            </p>
          </div>
          <span className="ml-auto hidden rounded-full border border-ok-line bg-white px-2.5 py-1 text-2xs font-semibold text-ok-ink sm:block">
            re-ran your suite
          </span>
        </div>
      </div>
    </div>
  );
}

function TestRow({ name, state }: { name: string; state: "pass" | "fail" }) {
  const failed = state === "fail";
  return (
    <li className="flex items-center gap-2 px-4 py-1.5">
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${failed ? "bg-danger" : "bg-ok"}`}
        aria-hidden
      />
      <span className={failed ? "font-semibold text-ink" : "text-muted"}>{name}</span>
      <span
        className={`ml-auto text-2xs font-semibold ${failed ? "text-danger-ink" : "text-ok-ink/70"}`}
      >
        {failed ? "FAIL" : "ok"}
      </span>
    </li>
  );
}
