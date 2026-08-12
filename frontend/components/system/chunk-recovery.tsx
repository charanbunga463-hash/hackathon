"use client";

/**
 * Recovers from `ChunkLoadError`.
 *
 * Next splits the app into per-route JavaScript chunks whose filenames carry a
 * build hash. A browser tab that was opened before a deploy still holds the old
 * route manifest, so the first navigation after the deploy asks for a chunk
 * filename that no longer exists on the server. The dynamic import rejects with
 * a ChunkLoadError and the user is left on a dead page — a red overlay in
 * development, a blank one in production — with no way forward but a manual
 * refresh they have no reason to know about.
 *
 * The fix is to reload once, which fetches the current manifest. Two details
 * make that safe rather than a hazard:
 *
 *   * a reload is attempted at most once per COOLDOWN_MS, recorded in
 *     sessionStorage. Without that, a chunk that is genuinely missing (a broken
 *     deploy, an offline CDN) would put the tab in an infinite reload loop,
 *     which is far worse than the error it replaces;
 *   * only ChunkLoadError is handled. Every other error propagates untouched,
 *     because silently reloading on an ordinary application bug would hide it.
 */

import * as React from "react";

const STORAGE_KEY = "apidoctor.chunk-reload-at";
const COOLDOWN_MS = 15_000;

function isChunkLoadError(value: unknown): boolean {
  if (!value) return false;
  const error = value as { name?: string; message?: string };
  if (error.name === "ChunkLoadError") return true;
  const message = String(error.message ?? value);
  // Webpack and Turbopack word this differently across versions, and the name
  // is lost entirely when the failure arrives as a plain string.
  return (
    message.includes("ChunkLoadError") ||
    /Loading chunk .* failed/i.test(message) ||
    /Failed to fetch dynamically imported module/i.test(message)
  );
}

function reloadOnce(): void {
  try {
    const last = Number(window.sessionStorage.getItem(STORAGE_KEY) ?? 0);
    if (Date.now() - last < COOLDOWN_MS) {
      // Already tried recently and still failing: this is a real outage, not a
      // stale tab. Leave the error visible rather than looping.
      return;
    }
    window.sessionStorage.setItem(STORAGE_KEY, String(Date.now()));
  } catch {
    // sessionStorage can throw in private mode. A single reload without the
    // guard is still better than a permanently dead page.
  }
  window.location.reload();
}

export function ChunkRecovery() {
  React.useEffect(() => {
    const onError = (event: ErrorEvent) => {
      if (isChunkLoadError(event.error ?? event.message)) reloadOnce();
    };
    const onRejection = (event: PromiseRejectionEvent) => {
      // The common shape: a failed dynamic import during route navigation.
      if (isChunkLoadError(event.reason)) reloadOnce();
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  return null;
}
