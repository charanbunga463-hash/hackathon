"use client";

import { CheckCircle2, CircleAlert, FileCode2, Zap } from "lucide-react";

import { usePointerParallax } from "./motion";

/**
 * The hero object: a repair session suspended in 3D.
 *
 * Four surfaces sit at four depths and drift against the pointer at four
 * different rates, which is what sells the space as real — parallax, not a
 * flat image with a tilt on it. The content is a genuine walk-through of the
 * product's own output (a failing test, the traceback, the patch, the verified
 * re-run), so the prettiest thing on the page is also the most honest.
 */
export function HeroScene() {
  const scene = usePointerParallax<HTMLDivElement>();

  return (
    <div ref={scene} className="scene relative mx-auto w-full max-w-lg">
      <div className="depth relative aspect-[4/3.4] w-full [transform:rotateX(calc(var(--py,0)*-9deg))_rotateY(calc(var(--px,0)*12deg))] transition-transform duration-500 ease-out motion-reduce:!transform-none">
        {/* ---------------------------------------------- layer 0: shadow -- */}
        <div className="absolute inset-x-8 bottom-2 h-16 rounded-[50%] bg-black/45 blur-2xl [transform:translateZ(-40px)]" />

        {/* ------------------------------------------ layer 1: test list --- */}
        <Layer depth={0} shift={10} className="left-0 top-6 w-[62%]">
          <Panel className="p-3.5">
            <Caption icon={FileCode2} text="tests/test_orders.py" />
            <ul className="mt-2.5 space-y-1.5 mono text-[10px] leading-none">
              <TestRow name="test_list_orders" state="pass" />
              <TestRow name="test_create_order" state="pass" />
              <TestRow name="test_order_total" state="fail" />
              <TestRow name="test_cancel_order" state="pass" />
            </ul>
          </Panel>
        </Layer>

        {/* ------------------------------------- layer 2: the traceback ---- */}
        <Layer depth={55} shift={22} className="right-0 top-0 w-[68%]">
          <Panel className="overflow-hidden">
            <div className="flex items-center gap-1.5 border-b border-line/70 px-3 py-2">
              <Dot className="bg-danger" />
              <Dot className="bg-warn" />
              <Dot className="bg-ok" />
              <span className="ml-1.5 text-[10px] text-faint">pytest</span>
              <span className="ml-auto flex items-center gap-1 rounded-full bg-danger/10 px-1.5 py-0.5 text-[9px] font-medium text-danger">
                <CircleAlert className="h-2.5 w-2.5" aria-hidden />1 failed
              </span>
            </div>

            {/* The scanline is the only thing that moves inside the panel; it
                reads as "this is live" without animating any text. */}
            <div className="relative overflow-hidden px-3 py-2.5">
              <span className="pointer-events-none absolute inset-x-0 top-0 h-6 bg-gradient-to-b from-accent/12 to-transparent animate-scan" />
              <pre className="mono text-[9.5px] leading-[1.65] text-muted">
                <span className="text-faint">app/services/</span>
                <span className="text-ink">orders.py</span>
                <span className="text-faint">:47</span>
                {"\n"}
                <span className="text-muted">    total += item.price * qty</span>
                {"\n"}
                <span className="text-danger">
                  TypeError: unsupported operand
                </span>
                {"\n"}
                <span className="text-danger">  &apos;NoneType&apos; and &apos;int&apos;</span>
              </pre>
            </div>
          </Panel>
        </Layer>

        {/* ---------------------------------------- layer 3: the patch ----- */}
        <Layer depth={100} shift={34} className="bottom-8 left-4 w-[74%]">
          <Panel className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-line/70 px-3 py-2">
              <Caption icon={Zap} text="Proposed patch" />
              <span className="mono text-[9px] text-faint">+1 −1</span>
            </div>
            <div className="mono space-y-px px-3 py-2 text-[9.5px] leading-[1.7]">
              <div className="diff-line-del -mx-3 px-3">
                <span className="text-faint">− </span>
                total += item.price * qty
              </div>
              <div className="diff-line-add -mx-3 px-3">
                <span className="text-faint">+ </span>
                total += (item.price or 0) * qty
              </div>
            </div>
          </Panel>
        </Layer>

        {/* ------------------------------------- layer 4: the verdict ------ */}
        <Layer depth={150} shift={48} className="-right-2 bottom-0 w-[52%]">
          <div className="glass edge-lit relative flex items-center gap-2.5 rounded-xl px-3.5 py-3 animate-float">
            <span className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ok/15 text-ok">
              <span className="absolute inset-0 animate-ping rounded-full bg-ok/20 [animation-duration:2.4s]" />
              <CheckCircle2 className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold leading-tight text-ink">
                Verified
              </p>
              <p className="mono text-[9px] leading-tight text-muted">
                4 passed · 0 failed
              </p>
            </div>
          </div>
        </Layer>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- pieces --- */

/**
 * One surface in the stack. `depth` places it along Z; `shift` is how far it
 * travels with the pointer — further forward means further travel, which is
 * exactly how parallax works in the world.
 */
function Layer({
  depth,
  shift,
  className,
  children,
}: {
  depth: number;
  shift: number;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`absolute ${className ?? ""}`}
      style={{
        transform: `translate3d(calc(var(--px,0) * ${shift}px), calc(var(--py,0) * ${shift}px), ${depth}px)`,
        transition: "transform 500ms cubic-bezier(0.16,1,0.3,1)",
      }}
    >
      {children}
    </div>
  );
}

function Panel({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`glass edge-lit relative rounded-xl ${className ?? ""}`}>
      {children}
    </div>
  );
}

function Caption({
  icon: Icon,
  text,
}: {
  icon: typeof FileCode2;
  text: string;
}) {
  return (
    <span className="flex items-center gap-1.5 text-[10px] font-medium text-muted">
      <Icon className="h-3 w-3 text-accent" aria-hidden />
      {text}
    </span>
  );
}

function Dot({ className }: { className: string }) {
  return <span className={`h-1.5 w-1.5 rounded-full ${className}`} />;
}

function TestRow({ name, state }: { name: string; state: "pass" | "fail" }) {
  const failed = state === "fail";
  return (
    <li className="flex items-center gap-1.5">
      <span
        className={`h-1 w-1 shrink-0 rounded-full ${failed ? "bg-danger" : "bg-ok"}`}
      />
      <span className={`truncate ${failed ? "text-ink" : "text-faint"}`}>
        {name}
      </span>
      <span
        className={`ml-auto text-[9px] ${failed ? "text-danger" : "text-ok/70"}`}
      >
        {failed ? "FAIL" : "ok"}
      </span>
    </li>
  );
}
