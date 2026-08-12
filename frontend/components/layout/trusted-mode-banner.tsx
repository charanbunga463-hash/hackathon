"use client";

import { ShieldAlert } from "lucide-react";

import { useAsync } from "@/hooks/useEvents";
import { getSandbox } from "@/lib/api";

/**
 * LOCAL TRUSTED MODE must be visible, not buried in settings.
 *
 * When the backend is not running project code in a container, the product says
 * so on every screen. Claiming sandbox-level isolation we do not have would be
 * exactly the kind of unverified claim this system exists to avoid.
 */
export function TrustedModeBanner() {
  const { data } = useAsync(getSandbox, []);
  if (!data || data.isolated) return null;

  return (
    <div className="flex items-start gap-2.5 border-b border-warn/30 bg-warn/10 px-5 py-2 lg:px-8">
      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warn" aria-hidden />
      <p className="text-xs leading-relaxed text-warn">
        <span className="font-semibold">LOCAL TRUSTED MODE</span> — project code runs
        directly on this host with no isolation. Timeouts and secret scrubbing are
        enforced; CPU, memory, filesystem and network are not restricted. Only load
        projects you trust. Start Docker and set{" "}
        <code className="mono rounded bg-warn/15 px-1">EXECUTION_MODE=docker</code> for a
        real sandbox.
      </p>
    </div>
  );
}
