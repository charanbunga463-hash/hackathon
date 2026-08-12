import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

import type { RepairVerdict, Severity } from "@/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDuration(ms: number): string {
  if (!ms || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export function formatRelative(iso?: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const delta = Date.now() - then;
  if (delta < 0) return "just now";
  const seconds = Math.floor(delta / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** The verdict vocabulary, rendered honestly. */
export const VERDICT_LABEL: Record<RepairVerdict, string> = {
  pending: "In progress",
  no_failure_detected: "No failure detected",
  awaiting_approval: "Awaiting approval",
  verified: "Fix verified",
  patch_applied_unverified: "Applied — not verified",
  repair_failed: "Repair failed",
  rejected_by_developer: "Rejected by developer",
  aborted: "Stopped safely",
  error: "Run failed",
};

export const VERDICT_TONE: Record<RepairVerdict, "ok" | "warn" | "danger" | "info" | "muted"> = {
  pending: "info",
  no_failure_detected: "muted",
  awaiting_approval: "warn",
  verified: "ok",
  patch_applied_unverified: "warn",
  repair_failed: "danger",
  rejected_by_developer: "muted",
  aborted: "warn",
  error: "danger",
};

export const SEVERITY_TONE: Record<Severity, "danger" | "warn" | "info" | "muted"> = {
  critical: "danger",
  high: "danger",
  medium: "warn",
  low: "info",
};

export function statusCodeTone(code?: number | null): "ok" | "warn" | "danger" | "muted" {
  if (!code) return "muted";
  if (code >= 500) return "danger";
  if (code >= 400) return "warn";
  if (code >= 200 && code < 300) return "ok";
  return "muted";
}

export function truncate(text: string, max = 120): string {
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export const STAGE_ORDER = [
  "observe",
  "investigate",
  "diagnose",
  "plan",
  "generate_patch",
  "validate_patch",
  "await_approval",
  "apply",
  "verify",
  "done",
] as const;

export const STAGE_LABEL: Record<string, string> = {
  observe: "Observe",
  investigate: "Investigate",
  diagnose: "Diagnose",
  plan: "Plan",
  generate_patch: "Generate patch",
  validate_patch: "Validate",
  await_approval: "Approval",
  apply: "Apply",
  verify: "Verify",
  retry: "Retry",
  done: "Done",
};
