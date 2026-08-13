"use client";

/**
 * Two steps on one route: verify the emailed code, then choose a new password.
 *
 * The code is exchanged for a short-lived, single-use ticket, and the ticket is
 * what authorises the change — so the second step cannot be reached by URL,
 * and a code that has been spent cannot be replayed.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Suspense } from "react";

import {
  AuthCard,
  Field,
  FormError,
  FormSuccess,
  OtpInput,
  PasswordInput,
  ResendButton,
  StrengthMeter,
  SubmitButton,
} from "@/components/auth/auth-form";
import {
  PASSWORD_MIN_LENGTH,
  errorMessage,
  getAuthConfig,
  resendOtp,
  resetPassword,
  validatePassword,
  verifyResetOtp,
} from "@/lib/auth";

const CODE_LENGTH = 6;

function ResetPasswordForm() {
  const router = useRouter();
  const params = useSearchParams();
  const email = params.get("email") ?? "";

  const [step, setStep] = React.useState<"code" | "password">("code");
  const [ticket, setTicket] = React.useState("");
  const [code, setCode] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [errors, setErrors] = React.useState<{ password?: string; confirm?: string }>({});
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [cooldown, setCooldown] = React.useState(60);

  React.useEffect(() => {
    getAuthConfig()
      .then((config) => setCooldown(config.resend_cooldown_seconds))
      .catch(() => undefined);
  }, []);

  React.useEffect(() => {
    if (!email) router.replace("/forgot-password");
  }, [email, router]);

  const submitCode = React.useCallback(
    async (submitted?: string) => {
      const value = submitted ?? code;
      if (value.length !== CODE_LENGTH || busy) return;
      setError(null);
      setNotice(null);
      setBusy(true);
      try {
        const result = await verifyResetOtp(email, value);
        setTicket(result.ticket);
        setStep("password");
      } catch (exc) {
        setError(errorMessage(exc, "Could not verify that code."));
        setCode("");
      } finally {
        setBusy(false);
      }
    },
    [busy, code, email],
  );

  const submitPassword = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);

    const next = {
      password: validatePassword(password, "", email) ?? undefined,
      confirm: password !== confirm ? "Passwords do not match." : undefined,
    };
    if (next.password || next.confirm) {
      setErrors(next);
      return;
    }
    setErrors({});
    setBusy(true);
    try {
      await resetPassword(ticket, password);
      // Every existing session was invalidated server-side, so the only way
      // forward is a fresh sign-in.
      router.replace("/login?reset=1");
    } catch (exc) {
      setError(errorMessage(exc, "Could not reset your password."));
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    setError(null);
    setNotice(null);
    try {
      const result = await resendOtp(email, "reset");
      setNotice(result.detail);
    } catch (exc) {
      setError(errorMessage(exc, "Could not send a new code."));
    }
  };

  if (step === "code") {
    return (
      <AuthCard title="Verify OTP">
        <p className="-mt-3 mb-5 text-xs leading-relaxed text-muted">
          Enter the code sent to{" "}
          <span className="font-medium text-ink">{email || "your email"}</span>. If an account
          exists for that address, the code is on its way.
        </p>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submitCode();
          }}
          className="space-y-4"
          noValidate
        >
          <FormError message={error} />
          <FormSuccess message={notice} />

          <OtpInput
            value={code}
            onChange={setCode}
            onComplete={(value) => void submitCode(value)}
            disabled={busy}
            length={CODE_LENGTH}
          />

          <SubmitButton loading={busy} disabled={code.length !== CODE_LENGTH}>
            {busy ? "Verifying…" : "Verify OTP"}
          </SubmitButton>
        </form>

        <div className="mt-5 space-y-2 text-center">
          <ResendButton cooldownSeconds={cooldown} onResend={resend} disabled={busy} />
          <p className="text-2xs text-faint">
            <Link href="/login" className="font-semibold text-brand-ink hover:underline">
              Back to Login
            </Link>
          </p>
        </div>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Reset Password" subtitle="Choose a new password for your account.">
      <form onSubmit={submitPassword} className="space-y-4" noValidate>
        <FormError message={error} />

        <Field label="New Password" htmlFor="password" error={errors.password}>
          <PasswordInput
            id="password"
            autoComplete="new-password"
            autoFocus
            placeholder={`At least ${PASSWORD_MIN_LENGTH} characters`}
            value={password}
            invalid={Boolean(errors.password)}
            disabled={busy}
            onChange={(event) => setPassword(event.target.value)}
          />
          <StrengthMeter value={password} />
        </Field>

        <Field label="Confirm Password" htmlFor="confirm" error={errors.confirm}>
          <PasswordInput
            id="confirm"
            autoComplete="new-password"
            placeholder="Repeat your new password"
            value={confirm}
            invalid={Boolean(errors.confirm)}
            disabled={busy}
            onChange={(event) => setConfirm(event.target.value)}
          />
        </Field>

        <SubmitButton loading={busy}>
          {busy ? "Resetting…" : "Reset Password"}
        </SubmitButton>
      </form>

      <p className="mt-4 text-center text-2xs text-faint">
        You will be signed out everywhere and asked to sign in again.
      </p>
    </AuthCard>
  );
}


/**
 * `useSearchParams` opts a route into client-side rendering, and the build
 * refuses to prerender it without a boundary to fall back to.
 */
export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="skeleton h-80 rounded-[1.25rem]" />}>
      <ResetPasswordForm />
    </Suspense>
  );
}
