"use client";

/**
 * The one-time warning that this instance runs uploaded code on the host.
 *
 * The left rail already shows the sandbox state permanently; this strip exists
 * to make sure the fact is *read at least once* per session rather than merely
 * being available. It dismisses to sessionStorage, so it returns for the next
 * visit rather than being silenced forever.
 */

import { ShieldAlert, X } from "lucide-react";
import * as React from "react";

import { useAsync } from "@/hooks/useEvents";
import { getSandbox } from "@/lib/api";

const DISMISS_KEY = "trusted_mode_banner_dismissed";

export function TrustedModeBanner() {
  const { data } = useAsync(getSandbox, []);
  // Starts dismissed so the banner can never flash in before we know whether
  // it applies.
  const [dismissed, setDismissed] = React.useState(true);

  React.useEffect(() => {
    if (!sessionStorage.getItem(DISMISS_KEY)) setDismissed(false);
  }, []);

  if (!data || data.isolated || dismissed) return null;

  return (
    <div className="mb-6 flex items-start gap-3 rounded-card border border-warn-line bg-warn-soft px-4 py-3 shadow-subtle animate-fade-up">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-warn/15 text-warn-ink">
        <ShieldAlert className="h-4 w-4" aria-hidden />
      </span>

      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold text-warn-ink">
          Local trusted mode — project code runs directly on this host
        </p>
        <p className="mt-0.5 text-2xs leading-relaxed text-warn-ink/80">
          There is no container boundary around an uploaded project. Set{" "}
          <code className="mono rounded bg-warn/15 px-1 py-0.5 font-semibold">
            EXECUTION_MODE=docker
          </code>{" "}
          to run every test and probe inside an isolated sandbox instead.
        </p>
      </div>

      <button
        onClick={() => {
          setDismissed(true);
          sessionStorage.setItem(DISMISS_KEY, "true");
        }}
        aria-label="Dismiss this notice"
        className="shrink-0 rounded-lg p-1.5 text-warn-ink/70 transition-colors hover:bg-warn/15 hover:text-warn-ink"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
