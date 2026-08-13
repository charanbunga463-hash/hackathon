import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { MarkA } from "@/components/marketing/mark-a";

/**
 * The public shell, restyled after antigravity.google: a thin, mostly-empty
 * white bar with a wordmark on the left, a centred set of section links, and a
 * single black pill call-to-action on the right. Nothing here is behind auth
 * and nothing calls the API, so the page paints instantly for a visitor.
 */

const NAV = [
  { href: "#pipeline", label: "How it works" },
  { href: "#capabilities", label: "Capabilities" },
  { href: "#trust", label: "Trust" },
  { href: "#scope", label: "Scope" },
];

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-surface">
      <header className="sticky top-0 z-50 border-b border-line/60 bg-surface/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-6 px-5 sm:px-8">
          <Link href="/" className="flex items-center gap-2.5">
            <MarkA className="h-6 w-6" />
            <span className="font-display text-base font-semibold tracking-tight text-ink">
              API&nbsp;Doctor
            </span>
          </Link>

          <nav
            className="hidden items-center gap-1 md:flex"
            aria-label="Sections"
          >
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="rounded-full px-3.5 py-2 text-sm font-medium text-muted transition-colors hover:bg-elevated hover:text-ink"
              >
                {item.label}
              </Link>
            ))}
          </nav>

          <div className="flex items-center gap-2">
            <Link
              href="/login"
              className="hidden rounded-full px-3.5 py-2 text-sm font-medium text-muted transition-colors hover:text-ink sm:inline-flex"
            >
              Log in
            </Link>
            <Link
              href="/register"
              className="group inline-flex items-center gap-1.5 rounded-full bg-ink px-4 py-2 text-sm font-semibold text-surface transition-transform duration-200 hover:-translate-y-px"
            >
              Get started
              <ArrowUpRight
                className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                aria-hidden
              />
            </Link>
          </div>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-line bg-surface">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-10 sm:flex-row sm:items-center sm:justify-between sm:px-8">
          <div className="flex items-center gap-2.5">
            <MarkA className="h-5 w-5" />
            <span className="font-display text-sm font-semibold text-ink">
              API Doctor
            </span>
            <span className="text-sm text-faint">
              Detect · Diagnose · Repair · Verify
            </span>
          </div>
          <p className="text-sm text-faint">
            Your code stays private to your account.
          </p>
        </div>
      </footer>
    </div>
  );
}
