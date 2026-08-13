import { Stethoscope } from "lucide-react";
import Link from "next/link";

/**
 * The public shell.
 *
 * Deliberately separate from `(app)`: nothing here is behind the auth guard and
 * nothing here calls the API, so the homepage renders instantly for a visitor
 * with no session and no account.
 */
export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-line/70 bg-white/70 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-5 sm:px-6">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-gradient text-white shadow-glow">
              <Stethoscope className="h-4.5 w-4.5" aria-hidden />
            </span>
            <span className="text-sm font-bold tracking-tight text-ink">API Doctor</span>
          </Link>

          <nav className="flex items-center gap-2" aria-label="Account">
            <Link
              href="/login"
              className="rounded-lg px-3.5 py-2 text-sm font-medium text-muted transition-colors hover:bg-elevated hover:text-ink"
            >
              Log in
            </Link>
            <Link
              href="/register"
              className="rounded-lg bg-brand-gradient px-4 py-2 text-sm font-semibold text-white shadow-glow transition-all duration-200 hover:-translate-y-px hover:shadow-glow-lg"
            >
              Get started
            </Link>
          </nav>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-line bg-white/60">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-5 py-8 text-xs text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p className="flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-brand-soft text-brand">
              <Stethoscope className="h-3 w-3" aria-hidden />
            </span>
            API Doctor — Detect. Diagnose. Repair. Verify.
          </p>
          <p className="text-faint">Your code stays private to your account.</p>
        </div>
      </footer>
    </div>
  );
}
