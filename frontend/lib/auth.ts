/**
 * Authentication client.
 *
 * The session lives in an HttpOnly cookie set by the backend, so there is no
 * token to read, store or attach here — and none for a script injected into
 * the page to steal. Every call goes through the same-origin `/api` rewrite
 * with `credentials: "include"`, which is what carries the cookie.
 */

import { ApiError, request } from "@/lib/api";
import type { UserPreferences } from "@/types";

export interface AuthUser {
  id: string;
  name: string;
  email: string;
  email_verified: boolean;
  created_at: string;
  preferences: UserPreferences;
}

export interface AuthConfig {
  accounts_enabled: boolean;
  allow_registration: boolean;
  otp_length: number;
  otp_ttl_seconds: number;
  resend_cooldown_seconds: number;
  password_min_length: number;
}

/** Either a session was created, or the address still needs verifying. */
export type AuthOutcome =
  | { status: "ok"; user: AuthUser }
  | { status: "verification_required"; email: string; detail: string };

export const getAuthConfig = () => request<AuthConfig>("/auth/config");

export const getMe = () => request<AuthUser>("/auth/me");

export const register = (name: string, email: string, password: string) =>
  request<AuthOutcome>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ name, email, password }),
  });

export const login = (email: string, password: string) =>
  request<AuthOutcome>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const verifyOtp = (email: string, code: string) =>
  request<{ status: string; user: AuthUser }>("/auth/verify-otp", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  });

export const resendOtp = (email: string, purpose: "verify" | "reset" = "verify") =>
  request<{ status: string; detail: string }>("/auth/resend-otp", {
    method: "POST",
    body: JSON.stringify({ email, purpose }),
  });

export const logout = () => request<{ status: string }>("/auth/logout", { method: "POST" });

export const forgotPassword = (email: string) =>
  request<{ status: string; detail: string }>("/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  });

export const verifyResetOtp = (email: string, code: string) =>
  request<{ status: string; ticket: string }>("/auth/verify-reset-otp", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  });

export const resetPassword = (ticket: string, password: string) =>
  request<{ status: string; detail: string }>("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ ticket, password }),
  });

/**
 * Turn any thrown value into something worth showing a user.
 *
 * The backend already answers with safe, human-readable messages; this only
 * has to cover transport failures, which otherwise surface as "Failed to fetch".
 */
export function errorMessage(exc: unknown, fallback = "Something went wrong. Please try again."): string {
  if (exc instanceof ApiError) return exc.detail || fallback;
  if (exc instanceof TypeError) return "Cannot reach the server. Check your connection.";
  if (exc instanceof Error && exc.message) return exc.message;
  return fallback;
}

/** The field name the backend blamed, when it named one. */
export function errorField(exc: unknown): string | null {
  return exc instanceof ApiError ? exc.field : null;
}

/* ------------------------------------------------- client-side validation --
 * Mirrors the server rules so the form can answer instantly. The server
 * revalidates everything; this is UX, never a security boundary.
 */

export const PASSWORD_MIN_LENGTH = 10;

export function validateEmail(value: string): string | null {
  const email = value.trim();
  if (!email) return "Enter your email address.";
  if (!/^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$/.test(email)) return "Enter a valid email address.";
  return null;
}

export function validateName(value: string): string | null {
  const name = value.trim();
  if (name.length < 2) return "Enter your name.";
  if (name.length > 80) return "Name must be at most 80 characters.";
  return null;
}

export function validatePassword(value: string, name = "", email = ""): string | null {
  if (!value) return "Enter a password.";
  if (value.length < PASSWORD_MIN_LENGTH)
    return `Password must be at least ${PASSWORD_MIN_LENGTH} characters.`;
  if (value.length > 200) return "Password must be at most 200 characters.";
  if (!/[A-Za-z]/.test(value)) return "Password must contain at least one letter.";
  if (!/[0-9]/.test(value)) return "Password must contain at least one number.";
  const lowered = value.toLowerCase();
  const local = email.trim().toLowerCase().split("@")[0];
  if (local && local.length >= 4 && lowered.includes(local))
    return "Password must not contain your email address.";
  if (name && name.trim().length >= 4 && lowered.includes(name.trim().toLowerCase()))
    return "Password must not contain your name.";
  return null;
}

/** 0–4, for the strength meter. Deliberately simple and honest. */
export function passwordStrength(value: string): number {
  if (!value) return 0;
  let score = 0;
  if (value.length >= PASSWORD_MIN_LENGTH) score += 1;
  if (value.length >= 14) score += 1;
  if (/[A-Z]/.test(value) && /[a-z]/.test(value)) score += 1;
  if (/[0-9]/.test(value) && /[^A-Za-z0-9]/.test(value)) score += 1;
  return score;
}
