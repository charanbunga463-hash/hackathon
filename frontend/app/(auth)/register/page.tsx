"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import {
  AuthCard,
  AuthInput,
  Field,
  FormError,
  PasswordInput,
  StrengthMeter,
  SubmitButton,
} from "@/components/auth/auth-form";
import {
  PASSWORD_MIN_LENGTH,
  errorField,
  errorMessage,
  register,
  validateEmail,
  validateName,
  validatePassword,
} from "@/lib/auth";

interface FieldErrors {
  name?: string;
  email?: string;
  password?: string;
  confirm?: string;
}

export default function RegisterPage() {
  const router = useRouter();

  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [errors, setErrors] = React.useState<FieldErrors>({});
  const [formError, setFormError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);

    const next: FieldErrors = {
      name: validateName(name) ?? undefined,
      email: validateEmail(email) ?? undefined,
      password: validatePassword(password, name, email) ?? undefined,
      confirm: password !== confirm ? "Passwords do not match." : undefined,
    };
    if (Object.values(next).some(Boolean)) {
      setErrors(next);
      return;
    }
    setErrors({});
    setBusy(true);
    try {
      const result = await register(name.trim(), email.trim(), password);
      const target = result.status === "ok" ? result.user.email : result.email;
      router.push(`/verify-otp?email=${encodeURIComponent(target)}`);
    } catch (exc) {
      const field = errorField(exc);
      const message = errorMessage(exc, "Could not create your account. Please try again.");
      if (field === "name" || field === "email" || field === "password") {
        setErrors({ [field]: message });
      } else {
        setFormError(message);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCard title="Create your account" subtitle="Your projects stay private to your account.">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <FormError message={formError} />

        <Field label="Name" htmlFor="name" error={errors.name}>
          <AuthInput
            id="name"
            autoComplete="name"
            autoFocus
            placeholder="Ada Lovelace"
            value={name}
            invalid={Boolean(errors.name)}
            disabled={busy}
            onChange={(event) => setName(event.target.value)}
          />
        </Field>

        <Field label="Email" htmlFor="email" error={errors.email}>
          <AuthInput
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@company.com"
            value={email}
            invalid={Boolean(errors.email)}
            disabled={busy}
            onChange={(event) => setEmail(event.target.value)}
          />
        </Field>

        <Field label="Password" htmlFor="password" error={errors.password}>
          <PasswordInput
            id="password"
            autoComplete="new-password"
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
            placeholder="Repeat your password"
            value={confirm}
            invalid={Boolean(errors.confirm)}
            disabled={busy}
            onChange={(event) => setConfirm(event.target.value)}
          />
        </Field>

        <SubmitButton loading={busy}>
          {busy ? "Creating account…" : "Create Account"}
        </SubmitButton>
      </form>

      <p className="mt-5 text-center text-xs text-muted">
        Already have an account?{" "}
        <Link href="/login" className="font-semibold text-brand-ink hover:underline">
          Login
        </Link>
      </p>
    </AuthCard>
  );
}
