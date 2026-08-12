import Link from "next/link";
import { Stethoscope } from "lucide-react";

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
      <header className="sticky top-0 z-40 border-b border-line bg-canvas/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-4 px-5 sm:px-6">
          <Link href="/" className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/15 text-accent">
              <Stethoscope className="h-4 w-4" aria-hidden />
            </span>
            <span className="text-sm font-semibold tracking-tight text-ink">
              API Doctor
            </span>
          </Link>

          <nav className="flex items-center gap-1.5" aria-label="Account">
            <Link
              href="/login"
              className="rounded-md px-3 py-1.5 text-sm text-muted transition-colors hover:bg-elevated hover:text-ink"
            >
              Login
            </Link>
            <Link
              href="/register"
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-accent/90"
            >
              Get started
            </Link>
          </nav>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-5xl flex-col gap-2 px-5 py-6 text-xs text-faint sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>API Doctor — Detect. Diagnose. Repair. Verify.</p>
          <p>Your code stays private to your account.</p>
        </div>
      </footer>
    </div>
  );
}
