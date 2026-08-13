"use client";

/**
 * The signed-out shell.
 *
 * A two-column split: the product's promise on the left, the form on the
 * right. On a phone the promise panel drops away entirely — someone signing in
 * from a phone wants the form, not the pitch.
 *
 * Anyone who already has a session is bounced to the dashboard, so the back
 * button after signing in does not land on a login form.
 */

import { CheckCircle2, FlaskConical, Lock, Stethoscope } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Backdrop } from "@/components/marketing/backdrop";
import { ApiError } from "@/lib/api";
import { getMe } from "@/lib/auth";

const PROMISES = [
  {
    icon: FlaskConical,
    title: "Runs your own tests",
    body: "Not a simulation. Your suite, your endpoints, real exit codes.",
  },
  {
    icon: CheckCircle2,
    title: "“Fixed” means verified",
    body: "A repair is only reported as fixed once the tests pass after the patch.",
  },
  {
    icon: Lock,
    title: "Private to your account",
    body: "Nobody else can list, open or run the projects you upload.",
  },
];

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    getMe()
      .then(() => {
        if (!cancelled) router.replace("/dashboard");
      })
      .catch((exc) => {
        if (!(exc instanceof ApiError) || exc.status !== 401) {
          console.error("session check failed", exc);
        }
        if (!cancelled) setChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="relative min-h-screen">
      <Backdrop dots={false} />

      <div className="mx-auto grid min-h-screen max-w-6xl items-center gap-12 px-5 py-10 lg:grid-cols-[1.05fr_26rem] lg:gap-16 lg:px-8">
        {/* ---------------------------------------------------------- pitch */}
        <section className="hidden lg:block">
          <Link href="/" className="inline-flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-brand-gradient text-white shadow-glow-lg">
              <Stethoscope className="h-5 w-5" aria-hidden />
            </span>
            <span>
              <span className="block text-base font-bold tracking-tight text-ink">
                API Doctor
              </span>
              <span className="block text-2xs text-faint">
                Detect · Diagnose · Repair · Verify
              </span>
            </span>
          </Link>

          <h2 className="mt-10 max-w-md text-4xl font-bold leading-[1.1] tracking-tight text-ink">
            Find what broke your API — <span className="text-gradient">and prove it is fixed.</span>
          </h2>
          <p className="mt-5 max-w-md text-sm leading-relaxed text-muted">
            Upload a project, and the agent runs your test suite, reads the real
            traceback, proposes the smallest patch that fixes it, and re-runs the
            tests to prove the result.
          </p>

          <ul className="mt-10 max-w-md space-y-3">
            {PROMISES.map(({ icon: Icon, title, body }) => (
              <li
                key={title}
                className="flex items-start gap-3 rounded-card border border-line bg-surface/70 p-3.5 shadow-subtle backdrop-blur"
              >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-brand-line bg-brand-soft text-brand">
                  <Icon className="h-4 w-4" aria-hidden />
                </span>
                <span className="min-w-0">
                  <span className="block text-xs font-semibold text-ink">{title}</span>
                  <span className="block text-2xs leading-relaxed text-muted">{body}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>

        {/* ----------------------------------------------------------- form */}
        <section className="mx-auto w-full max-w-sm">
          {/* The mark repeats here because on a phone the pitch panel is gone
              and the form would otherwise arrive unbranded. */}
          <Link
            href="/"
            className="mb-6 flex flex-col items-center gap-2.5 text-center lg:hidden"
          >
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-gradient text-white shadow-glow-lg">
              <Stethoscope className="h-5 w-5" aria-hidden />
            </span>
            <span>
              <span className="block text-sm font-bold tracking-tight text-ink">API Doctor</span>
              <span className="block text-2xs text-faint">Detect · Diagnose · Repair · Verify</span>
            </span>
          </Link>

          {/* Rendered only once we know there is no session, so a signed-in
              user never sees a flash of the login form before the redirect. */}
          <div className={checked ? "" : "invisible"}>{children}</div>

          <p className="mt-6 text-center text-2xs text-faint">
            Your projects are private to your account.
          </p>
        </section>
      </div>
    </div>
  );
}
