"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Suspense } from "react";

import {
  AuthCard,
  AuthInput,
  Field,
  FormError,
  PasswordInput,
  SubmitButton,
} from "@/components/auth/auth-form";
import { errorField, errorMessage, login, validateEmail } from "@/lib/auth";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [errors, setErrors] = React.useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  // Set by the reset flow, so a user who just changed their password is told
  // it worked instead of landing on a bare form.
  const notice = params.get("reset") === "1" ? "Password updated. Sign in to continue." : null;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);

    const emailError = validateEmail(email);
    const passwordError = password ? undefined : "Enter your password.";
    if (emailError || passwordError) {
      setErrors({ email: emailError ?? undefined, password: passwordError });
      return;
    }
    setErrors({});
    setBusy(true);
    try {
      const result = await login(email.trim(), password);
      if (result.status === "verification_required") {
        // Correct credentials, unfinished signup: continue where they left off.
        router.push(`/verify-otp?email=${encodeURIComponent(result.email)}`);
        return;
      }
      // Return them to whatever they were trying to reach, but only to a path
      // inside this app — an absolute URL here would be an open redirect.
      // `next` is set by the edge middleware when a signed-out visitor asked
      // for a page behind the guard. Only same-origin paths are honoured —
      // `//evil.com` is a protocol-relative URL, not a local path.
      const next = params.get("next");
      const safe = next && next.startsWith("/") && !next.startsWith("//");
      router.replace(safe ? next : "/dashboard");
      router.refresh();
    } catch (exc) {
      const field = errorField(exc);
      const message = errorMessage(exc, "Could not sign you in. Please try again.");
      if (field === "email" || field === "password") {
        setErrors({ [field]: message });
      } else {
        setFormError(message);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCard title="Welcome back" subtitle="Sign in to your API Doctor workspace.">
      <form onSubmit={submit} className="space-y-4" noValidate>
        {notice ? (
          <p className="rounded-md border border-ok/30 bg-ok/10 px-3 py-2 text-xs text-ok" role="status">
            {notice}
          </p>
        ) : null}
        <FormError message={formError} />

        <Field label="Email" htmlFor="email" error={errors.email}>
          <AuthInput
            id="email"
            type="email"
            autoComplete="email"
            autoFocus
            placeholder="you@company.com"
            value={email}
            invalid={Boolean(errors.email)}
            disabled={busy}
            onChange={(event) => setEmail(event.target.value)}
          />
        </Field>

        <Field
          label="Password"
          htmlFor="password"
          error={errors.password}
          hint={
            <Link href="/forgot-password" className="text-2xs text-accent hover:underline">
              Forgot password?
            </Link>
          }
        >
          <PasswordInput
            id="password"
            autoComplete="current-password"
            placeholder="••••••••••"
            value={password}
            invalid={Boolean(errors.password)}
            disabled={busy}
            onChange={(event) => setPassword(event.target.value)}
          />
        </Field>

        <SubmitButton loading={busy}>{busy ? "Signing in…" : "Login"}</SubmitButton>
      </form>

      <p className="mt-5 text-center text-xs text-muted">
        Don&apos;t have an account?{" "}
        <Link href="/register" className="text-accent hover:underline">
          Create account
        </Link>
      </p>
    </AuthCard>
  );
}


/**
 * `useSearchParams` opts a route into client-side rendering, and the build
 * refuses to prerender it without a boundary to fall back to.
 */
export default function LoginPage() {
  return (
    <Suspense fallback={<div className="panel h-64 animate-pulse" />}>
      <LoginForm />
    </Suspense>
  );
}
