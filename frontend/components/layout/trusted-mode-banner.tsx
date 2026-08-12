"use client";

import { ShieldAlert, X, ChevronRight, Server } from "lucide-react";
import * as React from "react";

import { useAsync } from "@/hooks/useEvents";
import { getSandbox } from "@/lib/api";

/**
 * LOCAL TRUSTED MODE Banner with dismiss capability and sleek styling.
 */
export function TrustedModeBanner() {
  const { data } = useAsync(getSandbox, []);
  const [dismissed, setDismissed] = React.useState<boolean>(true);

  React.useEffect(() => {
    // Check sessionStorage on mount
    const isDismissed = sessionStorage.getItem("trusted_mode_banner_dismissed");
    if (!isDismissed) {
      setDismissed(false);
    }
  }, []);

  const handleDismiss = () => {
    setDismissed(true);
    sessionStorage.setItem("trusted_mode_banner_dismissed", "true");
  };

  if (!data || data.isolated || dismissed) return null;

  return (
    <div className="relative border-b border-warn/25 bg-gradient-to-r from-warn/15 via-warn/10 to-transparent px-4 py-2.5 sm:px-6 lg:px-8 backdrop-blur-sm transition-all duration-300">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-warn/20 text-warn">
            <ShieldAlert className="h-3.5 w-3.5" aria-hidden />
          </span>
          <p className="leading-relaxed text-ink/90 min-w-0">
            <span className="font-semibold text-warn">LOCAL TRUSTED MODE</span>
            <span className="hidden sm:inline"> — project code runs directly on host (no isolation).</span>
            <span className="ml-1 text-muted hidden md:inline">
              Set <code className="mono rounded bg-warn/20 px-1 py-0.5 text-2xs text-warn font-medium">EXECUTION_MODE=docker</code> for sandbox isolation.
            </span>
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={handleDismiss}
            aria-label="Dismiss notice"
            className="flex items-center justify-center rounded-md p-1 text-muted hover:bg-warn/20 hover:text-ink transition-colors"
            title="Dismiss notification"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

