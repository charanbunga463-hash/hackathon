import {
  ArrowRight,
  CheckCircle2,
  FileSearch,
  FlaskConical,
  Lock,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { Backdrop } from "@/components/marketing/backdrop";
import { HeroScene } from "@/components/marketing/hero-scene";
import { Reveal, Tilt } from "@/components/marketing/motion";
import { Pipeline } from "@/components/marketing/pipeline";

/**
 * The public homepage.
 *
 * Every claim here is one the product actually makes good on — the four-stage
 * pipeline, the verification rule, the sandbox, per-account isolation. Nothing
 * is aspirational. The "What it works on" section exists specifically so a
 * visitor learns the real scope (Python, pytest) before signing up rather than
 * after uploading.
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
      <PipelineSection />
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
    <section className="relative overflow-hidden">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-24 lg:py-28">
        <div className="grid items-center gap-14 lg:grid-cols-[1.05fr_1fr] lg:gap-12">
          <div className="text-center lg:text-left">
            <Reveal>
              <span className="inline-flex items-center gap-2 rounded-full border border-brand-line bg-white/80 px-3.5 py-1.5 text-xs font-semibold text-brand-ink shadow-subtle backdrop-blur">
                <Sparkles className="h-3.5 w-3.5 text-brand" aria-hidden />
                Detect · Diagnose · Repair · Verify
              </span>
            </Reveal>

            <Reveal delay={80}>
              <h1 className="mt-6 text-4xl font-bold leading-[1.06] tracking-tight text-ink sm:text-5xl lg:text-[3.5rem]">
                Find out what is broken in your API —{" "}
                <span className="text-gradient">and prove it is fixed.</span>
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
                  className="group inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand-gradient px-6 py-3.5 text-sm font-semibold text-white shadow-glow-lg transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_20px_48px_-12px_rgb(var(--brand)/0.7)] sm:w-auto"
                >
                  Create your account
                  <ArrowRight
                    className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5"
                    aria-hidden
                  />
                </Link>
                <Link
                  href="/login"
                  className="inline-flex w-full items-center justify-center rounded-xl border border-line bg-white/80 px-6 py-3.5 text-sm font-semibold text-ink shadow-subtle backdrop-blur transition-colors hover:border-brand-line hover:bg-brand-soft hover:text-brand-ink sm:w-auto"
                >
                  I already have an account
                </Link>
              </div>
            </Reveal>

            <Reveal delay={320}>
              <p className="mt-5 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-xs text-faint lg:justify-start">
                <span className="flex items-center gap-1.5">
                  <CheckCircle2 className="h-3.5 w-3.5 text-ok" aria-hidden />
                  Free to start
                </span>
                <span className="flex items-center gap-1.5">
                  <Lock className="h-3.5 w-3.5 text-brand" aria-hidden />
                  Private to your account
                </span>
              </p>
            </Reveal>
          </div>

          <Reveal delay={200} className="lg:pl-4">
            <HeroScene />
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- pipeline -- */

function PipelineSection() {
  return (
    <section className="border-t border-line/70 bg-white/50">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-24">
        <Reveal>
          <SectionHeading
            eyebrow="The pipeline"
            title="Four stages, in order, every time"
            description="Each stage hands the next one real evidence. Nothing is skipped and nothing is assumed."
          />
        </Reveal>
        <Pipeline />
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
    <section className="border-t border-line/70">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-24">
        <Reveal>
          <SectionHeading
            eyebrow="Getting started"
            title="Three steps from upload to a verified fix"
          />
        </Reveal>

        <div className="mt-14 grid gap-5 sm:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, body }, index) => (
            <Reveal key={title} delay={index * 110}>
              <Tilt className="group h-full">
                <div className="card h-full p-6">
                  <div className="flex items-center gap-3">
                    <span className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-gradient text-sm font-bold tabular-nums text-white shadow-glow">
                      {index + 1}
                    </span>
                    <Icon className="h-4.5 w-4.5 text-brand" aria-hidden />
                  </div>
                  <h3 className="mt-5 text-lg font-bold tracking-tight text-ink">{title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">{body}</p>
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
    tone: "ok",
    title: "“Fixed” means tested",
    body: "A repair is only ever reported as verified when your test suite is run after the patch and actually passes. That verdict comes from the exit code, not from the AI — the model explains the result, it cannot change it.",
  },
  {
    icon: RotateCcw,
    tone: "brand",
    title: "Nothing is applied behind your back",
    body: "Every patch waits for your approval and is limited to a small, reviewable change. If verification fails, your workspace is rolled back to exactly how it was.",
  },
  {
    icon: Lock,
    tone: "grape",
    title: "Your code is yours",
    body: "Every project is scoped to your account — no one else can list it, open it, or run it. Your code runs in an isolated sandbox with credentials stripped from its environment.",
  },
  {
    icon: FileSearch,
    tone: "info",
    title: "Facts before opinions",
    body: "Status codes, timings, headers and test results are measured by the backend. The AI only interprets what was collected; it never invents a result.",
  },
] as const;

const GUARANTEE_TONE = {
  ok: "border-ok-line bg-ok-soft text-ok-ink",
  brand: "border-brand-line bg-brand-soft text-brand-ink",
  grape: "border-grape-line bg-grape-soft text-grape-ink",
  info: "border-info-line bg-info-soft text-info-ink",
};

function Guarantees() {
  return (
    <section className="border-t border-line/70 bg-white/50">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-6 sm:py-24">
        <Reveal>
          <SectionHeading
            eyebrow="Why you can trust the result"
            title="Built so a green tick means something"
            description="Debugging tools are only useful if you can believe them. These are the rules API Doctor holds itself to."
          />
        </Reveal>

        <div className="mt-14 grid gap-5 md:grid-cols-2">
          {GUARANTEES.map(({ icon: Icon, title, body, tone }, index) => (
            <Reveal key={title} delay={index * 90}>
              <Tilt className="group h-full" strength={4}>
                <div className="card h-full p-6">
                  <div className="flex items-center gap-3">
                    <span
                      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border ${GUARANTEE_TONE[tone]}`}
                    >
                      <Icon className="h-4.5 w-4.5" aria-hidden />
                    </span>
                    <h3 className="text-base font-bold tracking-tight text-ink">{title}</h3>
                  </div>
                  <p className="mt-3.5 text-sm leading-relaxed text-muted">{body}</p>
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
    <section className="border-t border-line/70">
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
            <div className="card space-y-6 p-6">
              <div>
                <h3 className="eyebrow">Frameworks detected</h3>
                <div className="mt-3 flex flex-wrap gap-2">
                  {FRAMEWORKS.map((name) => (
                    <span
                      key={name}
                      className="rounded-full border border-line bg-elevated px-3 py-1 text-xs font-medium text-muted transition-colors duration-200 hover:border-brand-line hover:bg-brand-soft hover:text-brand-ink"
                    >
                      {name}
                    </span>
                  ))}
                </div>
              </div>

              <div className="border-t border-line pt-5">
                <h3 className="eyebrow">Tests</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  Runs with <span className="mono font-semibold text-ink">pytest</span>, which
                  also picks up plain <span className="mono font-semibold text-ink">unittest</span>{" "}
                  files.
                </p>
              </div>

              <div className="border-t border-line pt-5">
                <h3 className="eyebrow">Endpoint testing</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  Works best when your app exposes an OpenAPI schema — API Doctor reads the real
                  contract instead of guessing at routes.
                </p>
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
    <section className="border-t border-line/70">
      <div className="mx-auto max-w-6xl px-5 py-20 sm:px-6 sm:py-24">
        <Reveal>
          <div className="relative overflow-hidden rounded-[1.75rem] border border-brand-line bg-brand-soft px-6 py-14 text-center shadow-raised sm:px-10 sm:py-16">
            {/* A single pool of light behind the ask. */}
            <div
              aria-hidden
              className="pointer-events-none absolute left-1/2 top-0 h-64 w-[40rem] max-w-full -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(circle,rgb(var(--brand)/0.3),transparent_70%)] blur-2xl"
            />
            <div className="relative">
              <h2 className="text-2xl font-bold tracking-tight text-ink sm:text-3xl">
                Stop guessing why your API is failing
              </h2>
              <p className="mx-auto mt-4 max-w-lg text-sm leading-relaxed text-muted">
                Upload a project and get a real answer — the failing line, the reason, and a fix
                proven by your own tests.
              </p>
              <Link
                href="/register"
                className="group mt-8 inline-flex items-center justify-center gap-2 rounded-xl bg-brand-gradient px-7 py-3.5 text-sm font-semibold text-white shadow-glow-lg transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_20px_48px_-12px_rgb(var(--brand)/0.7)]"
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
      <span className="eyebrow">{eyebrow}</span>
      <h2 className="mt-3 text-3xl font-bold tracking-tight text-ink sm:text-[2.1rem]">
        {title}
      </h2>
      {description ? (
        <p className={`mt-4 text-sm leading-relaxed text-muted ${centered ? "mx-auto" : ""}`}>
          {description}
        </p>
      ) : null}
    </div>
  );
}
