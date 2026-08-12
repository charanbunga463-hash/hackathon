"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Suspense } from "react";

import {
  AuthCard,
  FormError,
  FormSuccess,
  OtpInput,
  ResendButton,
  SubmitButton,
} from "@/components/auth/auth-form";
import { errorMessage, getAuthConfig, resendOtp, verifyOtp } from "@/lib/auth";

const CODE_LENGTH = 6;

function VerifyOtpForm() {
  const router = useRouter();
  const params = useSearchParams();
  const email = params.get("email") ?? "";

  const [code, setCode] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [cooldown, setCooldown] = React.useState(60);

  React.useEffect(() => {
    getAuthConfig()
      .then((config) => setCooldown(config.resend_cooldown_seconds))
      .catch(() => undefined);
  }, []);

  // Arriving here without an email means a bookmarked or hand-typed URL.
  React.useEffect(() => {
    if (!email) router.replace("/register");
  }, [email, router]);

  const submit = React.useCallback(
    async (submitted?: string) => {
      const value = submitted ?? code;
      if (value.length !== CODE_LENGTH || busy) return;
      setError(null);
      setNotice(null);
      setBusy(true);
      try {
        await verifyOtp(email, value);
        router.replace("/dashboard");
        router.refresh();
      } catch (exc) {
        setError(errorMessage(exc, "Could not verify that code."));
        setCode("");
      } finally {
        setBusy(false);
      }
    },
    [busy, code, email, router],
  );

  const resend = async () => {
    setError(null);
    setNotice(null);
    try {
      const result = await resendOtp(email, "verify");
      setNotice(result.detail);
    } catch (exc) {
      setError(errorMessage(exc, "Could not send a new code."));
    }
  };

  return (
    <AuthCard title="Verify your email">
      <p className="-mt-3 mb-5 text-xs leading-relaxed text-muted">
        We sent a verification code to{" "}
        <span className="font-medium text-ink">{email || "your email"}</span>.
      </p>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
        className="space-y-4"
        noValidate
      >
        <FormError message={error} />
        <FormSuccess message={notice} />

        <OtpInput
          value={code}
          onChange={setCode}
          onComplete={(value) => void submit(value)}
          disabled={busy}
          length={CODE_LENGTH}
        />

        <SubmitButton loading={busy} disabled={code.length !== CODE_LENGTH}>
          {busy ? "Verifying…" : "Verify OTP"}
        </SubmitButton>
      </form>

      <div className="mt-5 space-y-2 text-center">
        <p className="text-xs text-muted">
          Didn&apos;t receive the code?{" "}
          <ResendButton cooldownSeconds={cooldown} onResend={resend} disabled={busy} />
        </p>
        <p className="text-2xs text-faint">
          Wrong address?{" "}
          <Link href="/register" className="text-accent hover:underline">
            Start over
          </Link>
        </p>
      </div>
    </AuthCard>
  );
}


/**
 * `useSearchParams` opts a route into client-side rendering, and the build
 * refuses to prerender it without a boundary to fall back to.
 */
export default function VerifyOtpPage() {
  return (
    <Suspense fallback={<div className="panel h-64 animate-pulse" />}>
      <VerifyOtpForm />
    </Suspense>
  );
}
