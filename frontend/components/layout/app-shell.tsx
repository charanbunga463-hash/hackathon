"use client";

/**
 * The workspace chrome.
 *
 * A persistent left rail on desktop and a slide-over sheet on mobile. The rail
 * exists because this product has one durable question — "which project am I
 * looking at?" — and a horizontal bar answers it worse the more you add to it.
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
  ShieldCheck,
  Stethoscope,
  User as UserIcon,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { useAuth } from "@/components/auth/auth-context";
import { StatusDot } from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useEvents";
import { getSandbox } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV = [
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    hint: "Health at a glance",
  },
  {
    href: "/projects",
    label: "Projects",
    icon: FolderKanban,
    hint: "Everything you have uploaded",
  },
  {
    href: "/settings",
    label: "Settings",
    icon: SettingsIcon,
    hint: "Account and agent behaviour",
  },
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
    <div className="min-h-screen bg-canvas">
      {/* A wash of daylight behind the whole workspace. Fixed and behind
          everything, so no panel ever has to fight it for contrast. */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="aurora-blob absolute -left-40 -top-40 h-[32rem] w-[32rem] bg-brand/12" />
        <div className="aurora-blob absolute -right-32 top-24 h-[26rem] w-[26rem] bg-info/10" />
      </div>

      {/* ------------------------------------------------------- desktop rail */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-line bg-surface/80 backdrop-blur-xl lg:flex">
        <BrandMark />
        <NavList pathname={pathname} />
        <SandboxCard />
      </aside>

      {/* --------------------------------------------------------- mobile bar */}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-surface/85 px-4 backdrop-blur-xl lg:hidden">
        <button
          onClick={() => setMobileOpen(true)}
          aria-label="Open menu"
          aria-expanded={mobileOpen}
          className="rounded-lg p-2 text-muted transition-colors hover:bg-elevated hover:text-ink"
        >
          <Menu className="h-4.5 w-4.5" />
        </button>
        <Link href="/dashboard" className="flex items-center gap-2">
          <Logo className="h-8 w-8" />
          <span className="text-sm font-bold tracking-tight text-ink">API Doctor</span>
        </Link>
        <div className="ml-auto">
          <UserMenu />
        </div>
      </header>

      {/* ------------------------------------------------------ mobile sheet */}
      {mobileOpen ? (
        <div
          className="fixed inset-0 z-50 bg-ink/25 backdrop-blur-sm animate-fade-in lg:hidden"
          onClick={() => setMobileOpen(false)}
          role="presentation"
        >
          <div
            className="flex h-full w-72 max-w-[85vw] flex-col border-r border-line bg-surface shadow-pop"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between pr-3">
              <BrandMark />
              <button
                onClick={() => setMobileOpen(false)}
                aria-label="Close menu"
                className="rounded-lg p-2 text-muted transition-colors hover:bg-elevated hover:text-ink"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <NavList pathname={pathname} />
            <SandboxCard />
          </div>
        </div>
      ) : null}

      {/* ------------------------------------------------------------- page */}
      <div className="lg:pl-64">
        {/* The desktop-only top strip carries the account menu, so the rail
            stays purely navigational. */}
        <div className="sticky top-0 z-20 hidden h-14 items-center justify-end gap-3 border-b border-line bg-canvas/70 px-6 backdrop-blur-xl lg:flex">
          <UserMenu />
        </div>

        {/* min-w-0 so a wide child (a table, a stack trace) scrolls inside its
            own container instead of pushing the page sideways. */}
        <main className="mx-auto min-w-0 max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ parts -- */

export function Logo({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "flex items-center justify-center rounded-xl bg-brand-gradient text-white shadow-glow",
        className,
      )}
      aria-hidden
    >
      <Stethoscope className="h-1/2 w-1/2" />
    </span>
  );
}

function BrandMark() {
  return (
    <Link
      href="/dashboard"
      className="flex h-16 shrink-0 items-center gap-2.5 border-b border-line px-5"
    >
      <Logo className="h-9 w-9" />
      <span className="min-w-0">
        <span className="block text-sm font-bold leading-tight tracking-tight text-ink">
          API Doctor
        </span>
        <span className="block text-2xs leading-tight text-faint">
          Detect · Diagnose · Repair
        </span>
      </span>
    </Link>
  );
}

function NavList({ pathname }: { pathname: string }) {
  return (
    <nav className="flex-1 space-y-1 overflow-y-auto p-3" aria-label="Main">
      {NAV.map(({ href, label, icon: Icon, hint }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group flex items-start gap-3 rounded-xl px-3 py-2.5 transition-all duration-200",
              active
                ? "bg-brand-soft text-brand-ink shadow-subtle ring-1 ring-brand-line"
                : "text-muted hover:bg-elevated hover:text-ink",
            )}
          >
            <Icon
              className={cn(
                "mt-0.5 h-4 w-4 shrink-0 transition-colors",
                active ? "text-brand" : "text-faint group-hover:text-muted",
              )}
              aria-hidden
            />
            <span className="min-w-0">
              <span className="block text-sm font-semibold leading-tight">{label}</span>
              <span
                className={cn(
                  "block text-2xs leading-tight",
                  active ? "text-brand-ink/70" : "text-faint",
                )}
              >
                {hint}
              </span>
            </span>
          </Link>
        );
      })}
    </nav>
  );
}

/**
 * How this instance actually runs code, in the rail rather than buried in
 * Settings. It changes what an upload is allowed to do, so it should never be
 * more than a glance away.
 */
function SandboxCard() {
  const { data } = useAsync(getSandbox, []);
  const isolated = data?.isolated ?? false;

  return (
    <div className="shrink-0 border-t border-line p-3">
      <div
        className={cn(
          "rounded-xl border px-3 py-2.5",
          isolated ? "border-ok-line bg-ok-soft" : "border-warn-line bg-warn-soft",
        )}
      >
        <p className="flex items-center gap-2 text-2xs font-semibold uppercase tracking-wider">
          <StatusDot tone={isolated ? "ok" : "warn"} pulse={!isolated} />
          <span className={isolated ? "text-ok-ink" : "text-warn-ink"}>
            {isolated ? "Sandboxed" : "Local trusted"}
          </span>
        </p>
        <p className={cn("mt-1 text-2xs leading-relaxed", isolated ? "text-ok-ink/80" : "text-warn-ink/80")}>
          {isolated
            ? "Uploads run inside an isolated container."
            : "Uploads run on the host with no container isolation."}
        </p>
        <Link
          href="/settings"
          className="mt-1.5 inline-flex items-center gap-1 text-2xs font-semibold text-brand-ink hover:underline"
        >
          <ShieldCheck className="h-3 w-3" aria-hidden />
          Instance details
        </Link>
      </div>
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
        className="flex items-center gap-2 rounded-full border border-line bg-surface py-1 pl-1 pr-2.5 text-sm text-muted shadow-subtle transition-colors hover:border-brand-line hover:text-ink"
      >
        <span
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-gradient text-xs font-bold text-white"
          aria-hidden
        >
          {initial}
        </span>
        <span className="hidden max-w-[9rem] truncate font-medium md:inline">{user.name}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden />
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-2 w-64 overflow-hidden rounded-2xl border border-line bg-surface shadow-pop animate-scale-in"
        >
          <div className="flex items-center gap-3 border-b border-line bg-elevated/60 px-4 py-3">
            <span
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-gradient text-sm font-bold text-white"
              aria-hidden
            >
              {initial}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold text-ink" title={user.name}>
                {user.name}
              </span>
              <span className="block truncate text-2xs text-muted" title={user.email}>
                {user.email}
              </span>
            </span>
          </div>

          <div className="p-1.5">
            <MenuLink href="/settings" icon={UserIcon} label="Profile" />
            <MenuLink href="/settings" icon={SettingsIcon} label="Settings" />
          </div>

          <div className="border-t border-line p-1.5">
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
              className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-danger-ink transition-colors hover:bg-danger-soft disabled:opacity-60"
            >
              <LogOut className="h-4 w-4 shrink-0" aria-hidden />
              {signingOut ? "Signing out…" : "Log out"}
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
      className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-muted transition-colors hover:bg-elevated hover:text-ink"
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      {label}
    </Link>
  );
}
