"use client";

/**
 * The application chrome: a product name, three destinations, and the account.
 *
 * The navigation is deliberately short. Failures, repairs and run history are
 * facts *about a project*, so they live inside the project rather than as
 * top-level destinations that are empty until you have picked one. What is left
 * answers the only three questions a signed-in user has: where am I, where is
 * my work, and where are my settings.
 */

import {
  ChevronDown,
  FolderKanban,
  LayoutDashboard,
  LogOut,
  Menu,
  Settings as SettingsIcon,
  Stethoscope,
  User as UserIcon,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { useAuth } from "@/components/auth/auth-context";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = React.useState(false);

  // A route change should never leave the mobile sheet covering the page the
  // user just navigated to.
  React.useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4 sm:px-6">
          <Link href="/dashboard" className="flex shrink-0 items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/15 text-accent">
              <Stethoscope className="h-4 w-4" aria-hidden />
            </span>
            <span className="text-sm font-semibold tracking-tight text-ink">
              API Doctor
            </span>
          </Link>

          <nav className="ml-4 hidden items-center gap-1 sm:flex" aria-label="Main">
            {NAV.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                aria-current={isActive(pathname, href) ? "page" : undefined}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm transition-colors",
                  isActive(pathname, href)
                    ? "bg-elevated font-medium text-ink"
                    : "text-muted hover:bg-elevated/60 hover:text-ink",
                )}
              >
                {label}
              </Link>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <UserMenu />
            <button
              onClick={() => setMobileOpen((open) => !open)}
              aria-label={mobileOpen ? "Close menu" : "Open menu"}
              aria-expanded={mobileOpen}
              className="rounded-md p-2 text-muted hover:bg-elevated hover:text-ink sm:hidden"
            >
              {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
            </button>
          </div>
        </div>

        {mobileOpen ? (
          <nav className="border-t border-line px-4 py-2 sm:hidden" aria-label="Main">
            {NAV.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                aria-current={isActive(pathname, href) ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-2.5 py-2.5 text-sm",
                  isActive(pathname, href)
                    ? "bg-elevated font-medium text-ink"
                    : "text-muted",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden />
                {label}
              </Link>
            ))}
          </nav>
        ) : null}
      </header>

      {/* min-w-0 so a wide child (a table, a stack trace) scrolls inside its own
          container instead of pushing the page sideways. */}
      <main className="mx-auto min-w-0 max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
        {children}
      </main>
    </div>
  );
}

function UserMenu() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;

  const initial = (user.name.trim().charAt(0) || user.email.charAt(0)).toUpperCase();

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-2 rounded-md px-1.5 py-1.5 text-sm text-muted hover:bg-elevated hover:text-ink"
      >
        <span
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/15 text-xs font-semibold text-accent"
          aria-hidden
        >
          {initial}
        </span>
        <span className="hidden max-w-[10rem] truncate md:inline">{user.name}</span>
        <ChevronDown className="hidden h-3.5 w-3.5 md:inline" aria-hidden />
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1 w-60 overflow-hidden rounded-lg border border-line bg-surface shadow-lg"
        >
          <div className="border-b border-line px-3 py-2.5">
            <p className="truncate text-sm font-medium text-ink" title={user.name}>
              {user.name}
            </p>
            <p className="truncate text-xs text-faint" title={user.email}>
              {user.email}
            </p>
          </div>

          <div className="py-1">
            <MenuLink href="/settings" icon={UserIcon} label="Profile" />
            <MenuLink href="/settings" icon={SettingsIcon} label="Settings" />
          </div>

          <div className="border-t border-line py-1">
            <button
              role="menuitem"
              disabled={signingOut}
              onClick={async () => {
                setSigningOut(true);
                try {
                  await signOut();
                } finally {
                  setSigningOut(false);
                }
              }}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-muted hover:bg-elevated hover:text-ink disabled:opacity-60"
            >
              <LogOut className="h-4 w-4 shrink-0" aria-hidden />
              {signingOut ? "Signing out…" : "Logout"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MenuLink({
  href,
  icon: Icon,
  label,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}) {
  return (
    <Link
      href={href}
      role="menuitem"
      className="flex items-center gap-2.5 px-3 py-2 text-sm text-muted hover:bg-elevated hover:text-ink"
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      {label}
    </Link>
  );
}
