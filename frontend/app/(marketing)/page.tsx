import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  FileSearch,
  FlaskConical,
  GitPullRequestArrow,
  Lock,
  RotateCcw,
  ShieldCheck,
  Stethoscope,
  Upload,
} from "lucide-react";

/**
 * The public homepage.
 *
 * Every claim here is one the product actually makes good on — the four-stage
 * pipeline, the verification rule, the sandbox, per-account isolation. Nothing
 * is aspirational. The "What it works on" section exists specifically so a
 * visitor learns the real scope (Python, pytest) before signing up rather than
 * after uploading.
 */

export const metadata: Metadata = {
  title: "API Doctor — Find, explain and fix broken APIs",
  description:
    "Upload your API project. API Doctor runs your own tests, finds what is broken, explains why, proposes a minimal patch, and proves the fix by running the tests again.",
};

export default function HomePage() {
  return (
    <>
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
    <section className="border-b border-line">
      <div className="mx-auto max-w-5xl px-5 py-16 sm:px-6 sm:py-24">
        <div className="mx-auto max-w-2xl text-center">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-elevated px-3 py-1 text-xs text-muted">
            <Stethoscope className="h-3.5 w-3.5 text-accent" aria-hidden />
            Detect. Diagnose. Repair. Verify.
          </span>

          <h1 className="mt-6 text-3xl font-semibold leading-tight tracking-tight text-ink sm:text-4xl">
            Find out what is broken in your API —{" "}
            <span className="text-accent">and prove it is fixed.</span>
          </h1>

          <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-muted">
            Upload your project. API Doctor runs your own test suite, calls your
            real endpoints, finds what fails, explains why, and proposes a
            minimal patch. Then it runs your tests again to prove the fix
            actually worked.
          </p>

          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/register"
              className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent/90 sm:w-auto"
            >
              Create your account
              <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
            <Link
              href="/login"
              className="inline-flex w-full items-center justify-center rounded-md border border-line bg-surface px-5 py-2.5 text-sm font-medium text-ink transition-colors hover:bg-elevated sm:w-auto"
            >
              I already have an account
            </Link>
          </div>

          <p className="mt-4 text-xs text-faint">
            Free to start · Your code stays private to your account
          </p>
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- pipeline -- */

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

function Pipeline() {
  return (
    <section className="border-b border-line">
      <div className="mx-auto max-w-5xl px-5 py-14 sm:px-6 sm:py-20">
        <SectionHeading
          eyebrow="The pipeline"
          title="Four stages, in order, every time"
          description="Each stage hands the next one real evidence. Nothing is skipped and nothing is assumed."
        />

        <ol className="mt-10 grid gap-4 sm:grid-cols-2">
          {STAGES.map(({ icon: Icon, name, line, detail }, index) => (
            <li
              key={name}
              className="rounded-lg border border-line bg-surface p-5"
            >
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent/10 text-accent">
                  <Icon className="h-4.5 w-4.5" aria-hidden />
                </span>
                <div>
                  <span className="block text-2xs font-medium uppercase tracking-wide text-faint">
                    Step {index + 1}
                  </span>
                  <h3 className="text-sm font-semibold text-ink">{name}</h3>
                </div>
              </div>
              <p className="mt-3 text-sm text-ink">{line}</p>
              <p className="mt-1.5 text-xs leading-relaxed text-muted">{detail}</p>
            </li>
          ))}
        </ol>
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
    <section className="border-b border-line bg-surface/40">
      <div className="mx-auto max-w-5xl px-5 py-14 sm:px-6 sm:py-20">
        <SectionHeading
          eyebrow="Getting started"
          title="Three steps from upload to a verified fix"
        />

        <div className="mt-10 grid gap-6 sm:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, body }, index) => (
            <div key={title} className="relative">
              <div className="flex items-center gap-2.5">
                <span className="flex h-7 w-7 items-center justify-center rounded-full border border-line bg-canvas text-xs font-semibold tabular-nums text-accent">
                  {index + 1}
                </span>
                <Icon className="h-4 w-4 text-muted" aria-hidden />
              </div>
              <h3 className="mt-3 text-sm font-semibold text-ink">{title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">{body}</p>
            </div>
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
    <section className="border-b border-line">
      <div className="mx-auto max-w-5xl px-5 py-14 sm:px-6 sm:py-20">
        <SectionHeading
          eyebrow="Why you can trust the result"
          title="Built so a green tick means something"
          description="Debugging tools are only useful if you can believe them. These are the rules API Doctor holds itself to."
        />

        <div className="mt-10 grid gap-4 md:grid-cols-2">
          {GUARANTEES.map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="rounded-lg border border-line bg-surface p-5"
            >
              <div className="flex items-center gap-2.5">
                <Icon className="h-4 w-4 shrink-0 text-accent" aria-hidden />
                <h3 className="text-sm font-semibold text-ink">{title}</h3>
              </div>
              <p className="mt-2.5 text-sm leading-relaxed text-muted">{body}</p>
            </div>
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
    <section className="border-b border-line bg-surface/40">
      <div className="mx-auto max-w-5xl px-5 py-14 sm:px-6 sm:py-20">
        <div className="grid gap-8 md:grid-cols-2 md:gap-12">
          <div>
            <SectionHeading
              eyebrow="What it works on"
              title="Python API projects"
              description="Said plainly up front, so you know before you sign up rather than after you upload."
              align="left"
            />
          </div>

          <div className="space-y-5">
            <div>
              <h3 className="text-xs font-medium uppercase tracking-wide text-faint">
                Frameworks detected
              </h3>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {FRAMEWORKS.map((name) => (
                  <span
                    key={name}
                    className="rounded-md border border-line bg-canvas px-2 py-0.5 text-xs text-muted"
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
              <p className="mt-1.5 text-sm text-muted">
                Runs with <span className="mono text-ink">pytest</span>, which
                also picks up plain <span className="mono text-ink">unittest</span>{" "}
                files.
              </p>
            </div>

            <div>
              <h3 className="text-xs font-medium uppercase tracking-wide text-faint">
                Endpoint testing
              </h3>
              <p className="mt-1.5 text-sm text-muted">
                Works best when your app exposes an OpenAPI schema — API Doctor
                reads the real contract instead of guessing at routes.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ cta --- */

function CallToAction() {
  return (
    <section>
      <div className="mx-auto max-w-5xl px-5 py-16 sm:px-6 sm:py-20">
        <div className="rounded-xl border border-line bg-surface px-6 py-10 text-center sm:px-10 sm:py-14">
          <h2 className="text-2xl font-semibold tracking-tight text-ink">
            Stop guessing why your API is failing
          </h2>
          <p className="mx-auto mt-3 max-w-lg text-sm leading-relaxed text-muted">
            Upload a project and get a real answer — the failing line, the
            reason, and a fix proven by your own tests.
          </p>
          <Link
            href="/register"
            className="mt-7 inline-flex items-center justify-center gap-2 rounded-md bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent/90"
          >
            Get started
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        </div>
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
      <h2 className="mt-2 text-xl font-semibold tracking-tight text-ink sm:text-2xl">
        {title}
      </h2>
      {description ? (
        <p
          className={`mt-3 text-sm leading-relaxed text-muted ${
            centered ? "mx-auto" : ""
          }`}
        >
          {description}
        </p>
      ) : null}
    </div>
  );
}
