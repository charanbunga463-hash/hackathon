"use client";

/**
 * The authenticated shell.
 *
 * Everything under `(app)` renders inside it, so a page cannot be added to the
 * application without inheriting the guard. Unauthenticated visitors are sent
 * to /login rather than being shown a chrome full of empty panels.
 */

import { useRouter } from "next/navigation";
import * as React from "react";

import { AuthProvider, useAuth } from "@/components/auth/auth-context";
import { AppShell } from "@/components/layout/app-shell";
import { TrustedModeBanner } from "@/components/layout/trusted-mode-banner";
import { useTheme } from "@/components/theme/theme-provider";
import { Spinner } from "@/components/ui/primitives";

function Guard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  // The account's theme is authoritative once it has loaded; before that the
  // inline bootstrap in the root layout has already painted a reasonable guess.
  useTheme(user?.preferences?.theme);

  React.useEffect(() => {
    if (!loading && user === null) {
      router.replace("/login");
    }
  }, [loading, user, router]);

  if (loading || user === null) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2.5">
        <Spinner className="h-5 w-5" />
        <span className="text-sm text-muted">Loading your workspace…</span>
      </div>
    );
  }

  return (
    <AppShell>
      <TrustedModeBanner />
      {children}
    </AppShell>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <Guard>{children}</Guard>
    </AuthProvider>
  );
}
