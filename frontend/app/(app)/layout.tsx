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
import { AppShell, Logo } from "@/components/layout/app-shell";
import { TrustedModeBanner } from "@/components/layout/trusted-mode-banner";
import { Spinner } from "@/components/ui/primitives";

function Guard({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  React.useEffect(() => {
    if (!loading && user === null) {
      router.replace("/login");
    }
  }, [loading, user, router]);

  if (loading || user === null) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-canvas">
        <Logo className="h-12 w-12 animate-float" />
        <p className="flex items-center gap-2 text-sm text-muted">
          <Spinner className="h-4 w-4" />
          Loading your workspace…
        </p>
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
