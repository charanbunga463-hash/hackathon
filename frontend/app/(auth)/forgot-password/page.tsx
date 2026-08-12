"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import {
  AuthCard,
  AuthInput,
  Field,
  FormError,
  SubmitButton,
} from "@/components/auth/auth-form";
import { errorMessage, forgotPassword, validateEmail } from "@/lib/auth";

export default function ForgotPasswordPage() {
  const router = useRouter();
  const [email, setEmail] = React.useState("");
  const [fieldError, setFieldError] = React.useState<string | null>(null);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);

    const problem = validateEmail(email);
    if (problem) {
      setFieldError(problem);
      return;
    }
    setFieldError(null);
    setBusy(true);
    try {
      await forgotPassword(email.trim());
      // The backend answers identically whether or not the address is
      // registered, so this always advances — telling the user "no such
      // account" here would turn the form into a membership checker.
      router.push(`/reset-password?email=${encodeURIComponent(email.trim())}`);
    } catch (exc) {
      setFormError(errorMessage(exc, "Could not send a reset code. Please try again."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCard
      title="Forgot Password"
      subtitle="Enter your registered email and we'll send you a code."
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        <FormError message={formError} />

        <Field label="Email" htmlFor="email" error={fieldError}>
          <AuthInput
            id="email"
            type="email"
            autoComplete="email"
            autoFocus
            placeholder="you@company.com"
            value={email}
            invalid={Boolean(fieldError)}
            disabled={busy}
            onChange={(event) => setEmail(event.target.value)}
          />
        </Field>

        <SubmitButton loading={busy}>{busy ? "Sending…" : "Send OTP"}</SubmitButton>
      </form>

      <p className="mt-5 text-center text-xs text-muted">
        <Link href="/login" className="text-accent hover:underline">
          Back to Login
        </Link>
      </p>
    </AuthCard>
  );
}
