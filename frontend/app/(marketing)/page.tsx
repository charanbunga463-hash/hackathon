import {
  ArrowUpRight,
  Braces,
  CheckCircle2,
  FileSearch,
  FlaskConical,
  GitPullRequestArrow,
  Lock,
  RotateCcw,
  ScanSearch,
  ShieldCheck,
  TerminalSquare,
  Upload,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { HeroWave } from "@/components/marketing/hero-wave";
import { MarkA } from "@/components/marketing/mark-a";
import { Reveal } from "@/components/marketing/motion";

export const metadata: Metadata = {
  title: "API Doctor — Find, explain and fix broken APIs",
  description:
    "Upload your API project. API Doctor runs your own tests, finds what is broken, explains why, proposes a minimal patch, and proves the fix by running the tests again.",
};

export default function HomePage() {
  return (
    <>
      <Hero />
      <Stage />
      <Statement />
      <Pipeline />
      <Capabilities />
      <Trust />
      <Scope />
      <CallToAction />
    </>
  );
}

/* ------------------------------------------------------------------ hero -- */

function Hero() {
  return (
    <section className="relative overflow-hidden bg-surface">
      <div
        aria-hidden
        className="paper-grain pointer-events-none absolute inset-0"
      />
      <div className="relative mx-auto flex max-w-5xl flex-col items-center px-5 pb-16 pt-20 text-center sm:px-8 sm:pt-28">
        <Reveal>
          <span className="mb-8 inline-flex items-center gap-2 text-sm font-medium text-muted">
            <MarkA className="h-5 w-5" />
            API Doctor
          </span>
        </Reveal>

        <Reveal delay={80}>
          <h1 className="display text-5xl text-ink sm:text-6xl lg:text-[5.25rem]">
            Find what is broken.
            <br />
            Prove it is fixed.
          </h1>
        </Reveal>

        <Reveal delay={160}>
          <p className="mt-8 max-w-2xl text-pretty text-lg leading-relaxed text-muted">
            Upload your API project. API Doctor runs your own test suite, calls
            your real endpoints, explains every failure, and proposes a minimal
            patch — then runs the tests again to prove the repair actually
            worked.
          </p>
        </Reveal>

        <Reveal delay={240}>
          <div className="mt-10 flex flex-col items-center gap-3 sm:flex-row">
            <Link
              href="/register"
              className="group inline-flex w-full items-center justify-center gap-2 rounded-full bg-ink px-7 py-3.5 text-sm font-semibold text-surface transition-transform duration-200 hover:-translate-y-0.5 sm:w-auto"
            >
              Create your account
              <ArrowUpRight
                className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                aria-hidden
              />
            </Link>
            <Link
              href="/login"
              className="inline-flex w-full items-center justify-center rounded-full border border-line bg-elevated px-7 py-3.5 text-sm font-semibold text-ink transition-colors hover:bg-sunken sm:w-auto"
            >
              I already have an account
            </Link>
          </div>
        </Reveal>

        <Reveal delay={320}>
          <p className="mt-7 flex flex-wrap items-center justify-center gap-x-5 gap-y-1.5 text-sm text-faint">
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4 text-ok" aria-hidden />
              Free to start
            </span>
            <span className="flex items-center gap-1.5">
              <Lock className="h-4 w-4 text-brand" aria-hidden />
              Private to your account
            </span>
          </p>
        </Reveal>
      </div>
    </section>
  );
}

/* ----------------------------------------------------------------- stage -- */

/**
 * The dark centerpiece — the glowing rainbow particle wave on black, exactly
 * the beat antigravity.google builds its whole page around.
 */
function Stage() {
  return (
    <section className="relative bg-surface pb-20">
      <div className="mx-auto max-w-7xl px-4 sm:px-8">
        <div className="relative aspect-[16/10] w-full overflow-hidden rounded-[2rem] bg-black sm:aspect-[16/8] sm:rounded-[2.5rem]">
          <HeroWave />

          {/* Copy sits over the top of the stage, out of the wave's way. */}
          <div className="pointer-events-none absolute inset-x-0 top-0 flex flex-col items-center px-6 pt-10 text-center sm:pt-14">
            <span className="mb-3 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-medium uppercase tracking-[0.2em] text-white/70 backdrop-blur">
              The repair engine
            </span>
            <h2 className="display max-w-2xl text-3xl text-white sm:text-4xl">
              Evidence in. A verified fix out.
            </h2>
          </div>

          {/* Bottom vignette so the caption reads over the particles. */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-black/80 to-transparent"
          />
          <p className="absolute inset-x-0 bottom-6 mx-auto max-w-md px-6 text-center text-sm text-white/60">
            Rendered live — the same spectrum runs from a failing suite at the
            base to a proven pass at the crown.
          </p>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------- statement -- */

const CHIPS = [
  Upload,
  ScanSearch,
  FlaskConical,
  Braces,
  TerminalSquare,
  GitPullRequestArrow,
  CheckCircle2,
  ShieldCheck,
];

function Statement() {
  return (
    <section className="border-t border-line bg-surface">
      <div className="mx-auto max-w-6xl px-5 py-24 sm:px-8 sm:py-32">
        <Reveal>
          <div className="mb-12 flex flex-wrap justify-center gap-3">
            {CHIPS.map((Icon, i) => (
              <span
                key={i}
                className="flex h-12 w-12 items-center justify-center rounded-2xl border border-line bg-elevated text-muted"
              >
                <Icon className="h-5 w-5" aria-hidden />
              </span>
            ))}
          </div>
        </Reveal>

        <Reveal delay={120}>
          <p className="mx-auto max-w-4xl text-balance text-center font-display text-3xl font-medium leading-[1.15] tracking-tight text-ink sm:text-4xl lg:text-[3rem]">
            API Doctor is a diagnostic agent for your backend — it reads your
            real source and test output, finds the{" "}
            <span className="text-faint">exact broken line</span>, and never
            calls a fix done until your own tests say so.
          </p>
        </Reveal>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- pipeline -- */

const STAGES = [
  {
    icon: ScanSearch,
    label: "Detect",
    body: "Runs your suite and calls your endpoints to surface every failure, timeout and bad status — measured, not guessed.",
  },
  {
    icon: FileSearch,
    label: "Diagnose",
    body: "Traces each failure back to the responsible line in your source, with the real error and the test that caught it.",
  },
  {
    icon: GitPullRequestArrow,
    label: "Repair",
    body: "Proposes a small, reviewable patch scoped to the actual defect. Nothing is applied until you approve it.",
  },
  {
    icon: CheckCircle2,
    label: "Verify",
    body: "Re-runs your tests after the patch. A repair is reported fixed only when the suite actually passes.",
  },
];

function Pipeline() {
  return (
    <section id="pipeline" className="border-t border-line bg-elevated/50">
      <div className="mx-auto max-w-7xl px-5 py-24 sm:px-8 sm:py-28">
        <Reveal>
          <SectionHead
            eyebrow="How it works"
            title="Four stages, in order, every time"
            description="Each stage hands the next one real evidence. Nothing is skipped and nothing is assumed."
          />
        </Reveal>

        <div className="mt-16 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {STAGES.map(({ icon: Icon, label, body }, i) => (
            <Reveal key={label} delay={i * 90}>
              <div className="group h-full rounded-3xl border border-line bg-surface p-7 transition-colors hover:border-line-strong">
                <div className="flex items-center justify-between">
                  <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-ink text-surface">
                    <Icon className="h-5 w-5" aria-hidden />
                  </span>
                  <span className="font-display text-2xl font-semibold text-faint/60 tabular-nums">
                    0{i + 1}
                  </span>
                </div>
                <h3 className="mt-6 font-display text-xl font-semibold tracking-tight text-ink">
                  {label}
                </h3>
                <p className="mt-2.5 text-sm leading-relaxed text-muted">
                  {body}
                </p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------- capabilities -- */

const CAPS = [
  {
    icon: Upload,
    title: "Create a project",
    body: "Upload a .zip of your API. Any size. It gets its own isolated workspace, private to your account.",
  },
  {
    icon: FlaskConical,
    title: "Run a test",
    body: "Run your test suite, or point API Doctor at your endpoints and let it call them. Results appear in seconds.",
  },
  {
    icon: CheckCircle2,
    title: "Review and approve",
    body: "Read the diagnosis, look at the proposed diff, approve it — then watch the tests run again to confirm.",
  },
];

function Capabilities() {
  return (
    <section id="capabilities" className="border-t border-line bg-surface">
      <div className="mx-auto max-w-7xl px-5 py-24 sm:px-8 sm:py-28">
        <Reveal>
          <SectionHead
            eyebrow="Getting started"
            title="Three steps from upload to a verified fix"
          />
        </Reveal>

        <div className="mt-16 grid gap-4 sm:grid-cols-3">
          {CAPS.map(({ icon: Icon, title, body }, i) => (
            <Reveal key={title} delay={i * 100}>
              <div className="h-full rounded-3xl border border-line bg-elevated/60 p-8">
                <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-line bg-surface text-ink">
                  <Icon className="h-5 w-5" aria-hidden />
                </span>
                <h3 className="mt-6 font-display text-xl font-semibold tracking-tight text-ink">
                  {title}
                </h3>
                <p className="mt-2.5 text-sm leading-relaxed text-muted">
                  {body}
                </p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ----------------------------------------------------------------- trust -- */

const GUARANTEES = [
  {
    icon: ShieldCheck,
    title: "“Fixed” means tested",
    body: "A repair is only reported verified when your test suite runs after the patch and actually passes. That verdict comes from the exit code, not the model — the AI explains the result, it cannot change it.",
  },
  {
    icon: RotateCcw,
    title: "Nothing is applied behind your back",
    body: "Every patch waits for your approval and is limited to a small, reviewable change. If verification fails, your workspace is rolled back to exactly how it was.",
  },
  {
    icon: Lock,
    title: "Your code is yours",
    body: "Every project is scoped to your account — no one else can list it, open it, or run it. Your code runs in an isolated sandbox with credentials stripped from its environment.",
  },
  {
    icon: FileSearch,
    title: "Facts before opinions",
    body: "Status codes, timings, headers and test results are measured by the backend. The AI only interprets what was collected; it never invents a result.",
  },
];

function Trust() {
  return (
    <section id="trust" className="border-t border-line bg-elevated/50">
      <div className="mx-auto max-w-7xl px-5 py-24 sm:px-8 sm:py-28">
        <Reveal>
          <SectionHead
            eyebrow="Why you can trust the result"
            title="Built so a green tick means something"
            description="Debugging tools are only useful if you can believe them. These are the rules API Doctor holds itself to."
          />
        </Reveal>

        <div className="mt-16 grid gap-4 md:grid-cols-2">
          {GUARANTEES.map(({ icon: Icon, title, body }, i) => (
            <Reveal key={title} delay={i * 90}>
              <div className="flex h-full gap-4 rounded-3xl border border-line bg-surface p-7">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-ink text-surface">
                  <Icon className="h-5 w-5" aria-hidden />
                </span>
                <div>
                  <h3 className="font-display text-lg font-semibold tracking-tight text-ink">
                    {title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">
                    {body}
                  </p>
                </div>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ----------------------------------------------------------------- scope -- */

const FRAMEWORKS = [
  "FastAPI",
  "Flask",
  "Django",
  "Starlette",
  "Litestar",
  "Sanic",
  "aiohttp",
  "Tornado",
  "Quart",
  "Bottle",
];

function Scope() {
  return (
    <section id="scope" className="border-t border-line bg-surface">
      <div className="mx-auto grid max-w-7xl gap-12 px-5 py-24 sm:px-8 sm:py-28 md:grid-cols-[0.9fr_1.1fr]">
        <Reveal>
          <SectionHead
            align="left"
            eyebrow="What it works on"
            title="Python API projects"
            description="Said plainly up front, so you know before you sign up rather than after you upload."
          />
        </Reveal>

        <Reveal delay={120}>
          <div className="space-y-6 rounded-3xl border border-line bg-elevated/60 p-8">
            <div>
              <h3 className="eyebrow">Frameworks detected</h3>
              <div className="mt-3 flex flex-wrap gap-2">
                {FRAMEWORKS.map((name) => (
                  <span
                    key={name}
                    className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-sm font-medium text-muted"
                  >
                    {name}
                  </span>
                ))}
              </div>
            </div>

            <div className="border-t border-line pt-6">
              <h3 className="eyebrow">Tests</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                Runs with{" "}
                <span className="mono font-semibold text-ink">pytest</span>,
                which also picks up plain{" "}
                <span className="mono font-semibold text-ink">unittest</span>{" "}
                files.
              </p>
            </div>

            <div className="border-t border-line pt-6">
              <h3 className="eyebrow">Endpoint testing</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">
                Works best when your app exposes an OpenAPI schema — API Doctor
                reads the real contract instead of guessing at routes.
              </p>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ cta --- */

function CallToAction() {
  return (
    <section className="border-t border-line bg-surface">
      <div className="mx-auto max-w-7xl px-4 py-20 sm:px-8 sm:py-24">
        <Reveal>
          <div className="relative overflow-hidden rounded-[2rem] bg-black px-6 py-20 text-center sm:rounded-[2.5rem] sm:px-10 sm:py-28">
            <div
              aria-hidden
              className="pointer-events-none absolute left-1/2 top-1/2 h-[30rem] w-[40rem] max-w-full -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(circle,rgba(80,140,255,0.35),rgba(251,77,47,0.12)_55%,transparent_72%)] blur-3xl"
            />
            <div className="relative">
              <h2 className="display mx-auto max-w-3xl text-4xl text-white sm:text-5xl">
                Stop guessing why your API is failing
              </h2>
              <p className="mx-auto mt-6 max-w-xl text-pretty text-base leading-relaxed text-white/60">
                Upload a project and get a real answer — the failing line, the
                reason, and a fix proven by your own tests.
              </p>
              <Link
                href="/register"
                className="group mt-10 inline-flex items-center justify-center gap-2 rounded-full bg-surface px-8 py-4 text-sm font-semibold text-ink transition-transform duration-200 hover:-translate-y-0.5"
              >
                Get started free
                <ArrowUpRight
                  className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                  aria-hidden
                />
              </Link>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- shared --- */

function SectionHead({
  eyebrow,
  title,
  description,
  align = "center",
}: {
  eyebrow: string;
  title: string;
  description?: string;
  align?: "center" | "left";
}) {
  const centered = align === "center";
  return (
    <div className={centered ? "mx-auto max-w-2xl text-center" : "max-w-md"}>
      <span className="eyebrow">{eyebrow}</span>
      <h2 className="mt-4 font-display text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
        {title}
      </h2>
      {description ? (
        <p className="mt-4 text-base leading-relaxed text-muted">
          {description}
        </p>
      ) : null}
    </div>
  );
}
