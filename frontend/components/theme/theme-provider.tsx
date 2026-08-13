"use client";

/**
 * Applies the account's theme preference.
 *
 * The preference is stored on the account, so it follows the user to another
 * browser. It is also mirrored to localStorage for one reason: the account is
 * only known after `/api/auth/me` resolves, and repainting the whole page from
 * dark to light a beat after it loads is worse than a brief guess. The stored
 * copy is a rendering hint and nothing else — the account record decides.
 */

import * as React from "react";

import type { Theme } from "@/types";

const STORAGE_KEY = "apidoctor.theme";

function systemPrefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-color-scheme: dark)").matches
  );
}

/** Tailwind is configured for a `.dark` class on <html>; this sets it. */
export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  const dark = theme === "dark" || (theme === "system" && systemPrefersDark());
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

export function readStoredTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage?.getItem(STORAGE_KEY);
  return stored === "light" || stored === "dark" || stored === "system" ? stored : "light";
}

export function storeTheme(theme: Theme): void {
  try {
    window.localStorage?.setItem(STORAGE_KEY, theme);
  } catch {
    /* private mode; the account record is still authoritative */
  }
}

/**
 * Keeps <html> in sync with `theme`, and — while it is "system" — with the OS
 * setting changing underneath us.
 */
export function useTheme(theme: Theme | undefined): void {
  React.useEffect(() => {
    if (!theme) return;
    applyTheme(theme);
    storeTheme(theme);

    if (theme !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [theme]);
}

/**
 * Runs before React hydrates so the first paint is already the right colour.
 * Inlined into <head> by the root layout.
 */
export const THEME_BOOTSTRAP = `
(function () {
  try {
    var t = localStorage.getItem(${JSON.stringify(STORAGE_KEY)}) || "light";
    var dark = t === "dark" || (t === "system" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
  } catch (e) {}
})();
`;
