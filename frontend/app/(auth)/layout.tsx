"use client";

/**
 * The signed-out shell: a single centered card, no navigation.
 *
 * Anyone who already has a session is bounced to the dashboard, so the back
 * button after signing in does not land on a login form.
 */

import { Stethoscope } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Backdrop } from "@/components/marketing/backdrop";
import { ApiError } from "@/lib/api";
import { getMe } from "@/lib/auth";

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
    <div className="relative flex min-h-screen flex-col items-center justify-center px-4 py-10">
      <Backdrop />
      <div className="w-full max-w-sm">
        <div className="mb-7 flex flex-col items-center gap-2.5 text-center">
          <span className="flex h-11 w-11 animate-float items-center justify-center rounded-2xl bg-gradient-to-br from-accent to-info text-white shadow-[0_12px_30px_-8px_rgb(var(--accent)/0.7)]">
            <Stethoscope className="h-5 w-5" aria-hidden />
          </span>
          <div>
            <h1 className="text-base font-semibold tracking-tight text-ink">API Doctor</h1>
            <p className="text-2xs text-faint">Detect. Diagnose. Repair. Verify.</p>
          </div>
        </div>

        {/* Rendered only once we know there is no session, so a signed-in
            user never sees a flash of the login form before the redirect. */}
        <div className={checked ? "" : "invisible"}>{children}</div>
      </div>

      <p className="mt-8 text-center text-2xs text-faint">
        Your projects are private to your account.
      </p>
    </div>
  );
}
