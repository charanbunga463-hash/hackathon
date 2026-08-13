import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  FileSearch,
  FlaskConical,
  Lock,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  CheckCircle2,
  Upload,
} from "lucide-react";

import { Backdrop } from "@/components/marketing/backdrop";
import { HeroScene } from "@/components/marketing/hero-scene";
import { Reveal, Tilt } from "@/components/marketing/motion";
import { Pipeline3D } from "@/components/marketing/pipeline-3d";

/**
 * The public homepage.
 *
 * Every claim here is one the product actually makes good on — the four-stage
 * pipeline, the verification rule, the sandbox, per-account isolation. Nothing
 * is aspirational. The "What it works on" section exists specifically so a
 * visitor learns the real scope (Python, pytest) before signing up rather than
 * after uploading.
 *
 * The page is presented in depth: a parallax hero object, stages staged along
 * Z, and surfaces that respond to the pointer. The spectacle is load-bearing —
 * the hero object is a real repair session, and the pipeline's depth ordering
 * is the pipeline's actual order — so the first impression and the product
 * description are the same thing.
 *
 * This file stays a server component. Only the pieces that need a pointer or an
 * observer are client components, so the page still paints for a visitor with
 * no session and no JavaScript yet.
 */

export const metadata: Metadata = {
  title: "API Doctor — Find, explain and fix broken APIs",
  description:
    "Upload your API project. API Doctor runs your own tests, finds what is broken, explains why, proposes a minimal patch, and proves the fix by running the tests again.",
};

export default function HomePage() {
  return (
    <>
      <Backdrop />
      <Hero />
      <Pipeline />
      <HowItWorks />
      <Guarantees />
      <Scope />
      <CallToAction />
    </>
  );
}

/* ------------------------------------------------------------------ hero -- */

function Hero() {
  return (
    <section className="relative overflow-hidden border-b border-line/60">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-24 lg:py-28">
        <div className="grid items-center gap-14 lg:grid-cols-[1.05fr_1fr] lg:gap-10">
          {/* ----------------------------------------------------- copy -- */}
          <div className="text-center lg:text-left">
            <Reveal>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface/70 px-3 py-1 text-xs text-muted backdrop-blur">
                <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden />
                Detect. Diagnose. Repair. Verify.
              </span>
            </Reveal>

            <Reveal delay={80}>
              <h1 className="mt-6 text-4xl font-semibold leading-[1.08] tracking-tight text-ink sm:text-5xl lg:text-[3.4rem]">
                Find out what is broken in your API —{" "}
                <span className="text-glow">and prove it is fixed.</span>
              </h1>
            </Reveal>

            <Reveal delay={160}>
              <p className="mx-auto mt-6 max-w-xl text-base leading-relaxed text-muted lg:mx-0">
                Upload your project. API Doctor runs your own test suite, calls
                your real endpoints, finds what fails, explains why, and proposes
                a minimal patch. Then it runs your tests again to prove the fix
                actually worked.
              </p>
            </Reveal>

            <Reveal delay={240}>
              <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row lg:justify-start">
                <Link
                  href="/register"
                  className="group inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-6 py-3 text-sm font-medium text-white shadow-[0_10px_36px_-10px_rgb(var(--accent)/0.9)] transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_16px_44px_-10px_rgb(var(--accent)/1)] sm:w-auto"
                >
                  Create your account
                  <ArrowRight
                    className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5"
                    aria-hidden
                  />
                </Link>
                <Link
                  href="/login"
                  className="inline-flex w-full items-center justify-center rounded-lg border border-line bg-surface/70 px-6 py-3 text-sm font-medium text-ink backdrop-blur transition-colors hover:bg-elevated sm:w-auto"
                >
                  I already have an account
                </Link>
              </div>
            </Reveal>

            <Reveal delay={320}>
              <p className="mt-5 text-xs text-faint">
                Free to start · Your code stays private to your account
              </p>
            </Reveal>
          </div>

          {/* ---------------------------------------------------- scene -- */}
          <Reveal delay={200} className="lg:pl-4">
            <HeroScene />
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- pipeline -- */

function Pipeline() {
  return (
    <section className="border-b border-line/60">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-24">
        <Reveal>
          <SectionHeading
            eyebrow="The pipeline"
            title="Four stages, in order, every time"
            description="Each stage hands the next one real evidence. Nothing is skipped and nothing is assumed."
          />
        </Reveal>
        <Pipeline3D />
      </div>
    </section>
  );
}

/* ---------------------------------------------------------- how it works -- */

const STEPS = [
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

function HowItWorks() {
  return (
    <section className="border-b border-line/60">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-24">
        <Reveal>
          <SectionHeading
            eyebrow="Getting started"
            title="Three steps from upload to a verified fix"
          />
        </Reveal>

        <div className="mt-12 grid gap-5 sm:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, body }, index) => (
            <Reveal key={title} delay={index * 110}>
              <Tilt className="group h-full">
                <div className="glass edge-lit relative h-full overflow-hidden rounded-xl p-6">
                  <div
                    className="flex items-center gap-3"
                    style={{ transform: "translateZ(24px)" }}
                  >
                    <span className="flex h-8 w-8 items-center justify-center rounded-full border border-line bg-canvas/80 text-xs font-semibold tabular-nums text-accent">
                      {index + 1}
                    </span>
                    <Icon className="h-4 w-4 text-muted" aria-hidden />
                  </div>
                  <div style={{ transform: "translateZ(14px)" }}>
                    <h3 className="mt-4 text-base font-semibold text-ink">
                      {title}
                    </h3>
                    <p className="mt-2 text-sm leading-relaxed text-muted">
                      {body}
                    </p>
                  </div>
                </div>
              </Tilt>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ guarantees -- */

const GUARANTEES = [
  {
    icon: ShieldCheck,
    title: "“Fixed” means tested",
    body: "A repair is only ever reported as verified when your test suite is run after the patch and actually passes. That verdict comes from the exit code, not from the AI — the model explains the result, it cannot change it.",
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

function Guarantees() {
  return (
    <section className="border-b border-line/60">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-24">
        <Reveal>
          <SectionHeading
            eyebrow="Why you can trust the result"
            title="Built so a green tick means something"
            description="Debugging tools are only useful if you can believe them. These are the rules API Doctor holds itself to."
          />
        </Reveal>

        <div className="mt-12 grid gap-5 md:grid-cols-2">
          {GUARANTEES.map(({ icon: Icon, title, body }, index) => (
            <Reveal key={title} delay={index * 90}>
              <Tilt className="group h-full" strength={6}>
                <div className="glass edge-lit relative h-full rounded-xl p-6">
                  <div style={{ transform: "translateZ(20px)" }}>
                    <div className="flex items-center gap-2.5">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent transition-shadow duration-500 group-hover:shadow-[0_0_24px_-4px_rgb(var(--accent)/0.7)]">
                        <Icon className="h-4 w-4" aria-hidden />
                      </span>
                      <h3 className="text-base font-semibold text-ink">
                        {title}
                      </h3>
                    </div>
                    <p className="mt-3 text-sm leading-relaxed text-muted">
                      {body}
                    </p>
                  </div>
                </div>
              </Tilt>
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
    <section className="border-b border-line/60">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-24">
        <div className="grid gap-10 md:grid-cols-2 md:gap-14">
          <Reveal>
            <SectionHeading
              eyebrow="What it works on"
              title="Python API projects"
              description="Said plainly up front, so you know before you sign up rather than after you upload."
              align="left"
            />
          </Reveal>

          <Reveal delay={120}>
            <div className="glass rounded-xl p-6">
              <div className="space-y-6">
                <div>
                  <h3 className="text-xs font-medium uppercase tracking-wide text-faint">
                    Frameworks detected
                  </h3>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {FRAMEWORKS.map((name) => (
                      <span
                        key={name}
                        className="rounded-md border border-line bg-canvas/70 px-2.5 py-1 text-xs text-muted transition-colors duration-300 hover:border-accent/50 hover:text-ink"
                      >
                        {name}
                      </span>
                    ))}
                  </div>
                </div>

                <div>
                  <h3 className="text-xs font-medium uppercase tracking-wide text-faint">
                    Tests
                  </h3>
                  <p className="mt-2 text-sm text-muted">
                    Runs with <span className="mono text-ink">pytest</span>,
                    which also picks up plain{" "}
                    <span className="mono text-ink">unittest</span> files.
                  </p>
                </div>

                <div>
                  <h3 className="text-xs font-medium uppercase tracking-wide text-faint">
                    Endpoint testing
                  </h3>
                  <p className="mt-2 text-sm text-muted">
                    Works best when your app exposes an OpenAPI schema — API
                    Doctor reads the real contract instead of guessing at routes.
                  </p>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ cta --- */

function CallToAction() {
  return (
    <section>
      <div className="mx-auto max-w-6xl px-5 py-20 sm:px-6 sm:py-24">
        <Reveal>
          <div className="glass edge-lit relative overflow-hidden rounded-2xl px-6 py-14 text-center sm:px-10 sm:py-16">
            {/* A single pool of light behind the ask. */}
            <div
              aria-hidden
              className="pointer-events-none absolute left-1/2 top-0 h-56 w-[36rem] max-w-full -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(circle,rgb(var(--accent)/0.28),transparent_70%)] blur-2xl"
            />
            <div className="relative">
              <h2 className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
                Stop guessing why your API is failing
              </h2>
              <p className="mx-auto mt-4 max-w-lg text-sm leading-relaxed text-muted">
                Upload a project and get a real answer — the failing line, the
                reason, and a fix proven by your own tests.
              </p>
              <Link
                href="/register"
                className="group mt-8 inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-6 py-3 text-sm font-medium text-white shadow-[0_10px_36px_-10px_rgb(var(--accent)/0.9)] transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_16px_44px_-10px_rgb(var(--accent)/1)]"
              >
                Get started
                <ArrowRight
                  className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5"
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

/* -------------------------------------------------------------- shared ---- */

function SectionHeading({
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
    <div className={centered ? "mx-auto max-w-2xl text-center" : ""}>
      <span className="text-xs font-medium uppercase tracking-wide text-accent">
        {eyebrow}
      </span>
      <h2 className="mt-2.5 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
        {title}
      </h2>
      {description ? (
        <p
          className={`mt-4 text-sm leading-relaxed text-muted ${
            centered ? "mx-auto" : ""
          }`}
        >
          {description}
        </p>
      ) : null}
    </div>
  );
}
