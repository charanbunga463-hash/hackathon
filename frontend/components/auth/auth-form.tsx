"use client";

/**
 * Shared pieces for the sign-in, registration, OTP and reset forms.
 *
 * They exist so the five auth screens behave identically: the same field
 * markup and error placement, the same disabled-while-submitting rule, the
 * same success and failure notes. Inputs are the app's own `Input` primitive,
 * so a text field looks the same signed out as it does in Settings.
 */

import { AlertCircle, CheckCircle2, Eye, EyeOff, Loader2 } from "lucide-react";
import * as React from "react";

import { Input } from "@/components/ui/primitives";
import { passwordStrength } from "@/lib/auth";
import { cn } from "@/lib/utils";

export function AuthCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-[1.25rem] border border-line bg-surface p-6 shadow-pop animate-fade-up sm:p-7">
      <div className="mb-6">
        <h2 className="text-xl font-bold tracking-tight text-ink">{title}</h2>
        {subtitle ? (
          <p className="mt-1.5 text-xs leading-relaxed text-muted">{subtitle}</p>
        ) : null}
      </div>
      {children}
    </div>
  );
}

export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  error?: string | null;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={htmlFor} className="text-xs font-semibold text-ink">
          {label}
        </label>
        {hint}
      </div>
      {children}
      {error ? (
        <p id={`${htmlFor}-error`} className="text-2xs font-medium text-danger-ink" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export const AuthInput = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }
>(({ invalid, ...props }, ref) => (
  <Input
    ref={ref}
    invalid={invalid}
    aria-describedby={invalid ? `${props.id}-error` : undefined}
    {...props}
  />
));
AuthInput.displayName = "AuthInput";

export function PasswordInput({
  invalid,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }) {
  const [visible, setVisible] = React.useState(false);
  return (
    <div className="relative">
      <AuthInput
        {...props}
        invalid={invalid}
        type={visible ? "text" : "password"}
        className="pr-10"
      />
      <button
        type="button"
        onClick={() => setVisible((value) => !value)}
        aria-label={visible ? "Hide password" : "Show password"}
        className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-faint transition-colors hover:bg-elevated hover:text-muted"
        tabIndex={-1}
      >
        {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}

/** Four segments that fill as the password gets stronger. */
export function StrengthMeter({ value }: { value: string }) {
  const score = passwordStrength(value);
  const labels = ["", "Weak", "Fair", "Good", "Strong"];
  const fills = ["bg-line", "bg-danger", "bg-warn", "bg-info", "bg-ok"];
  const texts = ["", "text-danger-ink", "text-warn-ink", "text-info-ink", "text-ok-ink"];
  if (!value) return null;
  return (
    <div className="flex items-center gap-2 pt-1">
      <div className="flex h-1.5 flex-1 gap-1">
        {[1, 2, 3, 4].map((step) => (
          <span
            key={step}
            className={cn(
              "h-full flex-1 rounded-full transition-colors duration-300",
              step <= score ? fills[score] : "bg-line",
            )}
          />
        ))}
      </div>
      <span className={cn("w-12 text-right text-2xs font-semibold", texts[score])}>
        {labels[score]}
      </span>
    </div>
  );
}

export function SubmitButton({
  loading,
  children,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) {
  return (
    <button
      type="submit"
      // Disabled while in flight so a double-click cannot register twice or
      // burn two OTP sends.
      disabled={loading || props.disabled}
      className={cn(
        "flex w-full items-center justify-center gap-2 rounded-xl bg-brand-gradient px-4 py-3",
        "text-sm font-semibold text-white shadow-glow transition-all duration-200",
        "hover:-translate-y-px hover:shadow-glow-lg",
        "disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-glow",
        className,
      )}
      {...props}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
      {children}
    </button>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-xl border border-danger-line bg-danger-soft px-3.5 py-2.5 text-xs font-medium text-danger-ink"
    >
      <AlertCircle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}

export function FormSuccess({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div
      role="status"
      className="flex items-start gap-2 rounded-xl border border-ok-line bg-ok-soft px-3.5 py-2.5 text-xs font-medium text-ok-ink"
    >
      <CheckCircle2 className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}

/**
 * Six single-character boxes that behave like one input: paste fills them all,
 * backspace steps back, and a complete code submits without another click.
 */
export function OtpInput({
  value,
  onChange,
  onComplete,
  disabled,
  length = 6,
}: {
  value: string;
  onChange: (value: string) => void;
  onComplete?: (value: string) => void;
  disabled?: boolean;
  length?: number;
}) {
  const refs = React.useRef<(HTMLInputElement | null)[]>([]);

  // A fixed-length array of slots, never a ragged string. Writing straight
  // into `value.split("")` at an index past its end leaves holes that `join`
  // silently drops, so clicking box 4 of an empty field put the digit in box 1.
  const slots = React.useMemo(() => {
    const filled = Array.from({ length }, () => "");
    value
      .replace(/\D/g, "")
      .slice(0, length)
      .split("")
      .forEach((digit, index) => {
        filled[index] = digit;
      });
    return filled;
  }, [value, length]);

  const commit = (next: string[]) => {
    // Slots are positional; the value is the compacted code.
    const code = next.join("").replace(/\D/g, "").slice(0, length);
    onChange(code);
    if (code.length === length) onComplete?.(code);
  };

  const handleChange = (index: number, raw: string) => {
    const typed = raw.replace(/\D/g, "");
    if (!typed) return;
    const next = [...slots];
    // Typing over a filled box replaces it; a paste spills into the rest.
    for (let offset = 0; offset < typed.length && index + offset < length; offset += 1) {
      next[index + offset] = typed[offset];
    }
    commit(next);
    refs.current[Math.min(index + typed.length, length - 1)]?.focus();
  };

  const handleKeyDown = (index: number, event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Backspace") {
      event.preventDefault();
      const next = [...slots];
      if (next[index]) {
        next[index] = "";
        commit(next);
      } else if (index > 0) {
        next[index - 1] = "";
        commit(next);
        refs.current[index - 1]?.focus();
      }
    } else if (event.key === "ArrowLeft" && index > 0) {
      refs.current[index - 1]?.focus();
    } else if (event.key === "ArrowRight" && index < length - 1) {
      refs.current[index + 1]?.focus();
    }
  };

  return (
    <div className="flex justify-between gap-2" role="group" aria-label="Verification code">
      {Array.from({ length }).map((_, index) => (
        <input
          key={index}
          ref={(node) => {
            refs.current[index] = node;
          }}
          value={slots[index] ?? ""}
          onChange={(event) => handleChange(index, event.target.value)}
          onKeyDown={(event) => handleKeyDown(index, event)}
          onPaste={(event) => {
            // Pasting the whole code is how most people enter one.
            event.preventDefault();
            const pasted = event.clipboardData
              .getData("text")
              .replace(/\D/g, "")
              .slice(0, length);
            if (!pasted) return;
            const next = Array.from({ length }, (_, slot) => pasted[slot] ?? "");
            commit(next);
            refs.current[Math.min(pasted.length, length - 1)]?.focus();
          }}
          onFocus={(event) => event.target.select()}
          disabled={disabled}
          inputMode="numeric"
          autoComplete={index === 0 ? "one-time-code" : "off"}
          aria-label={`Digit ${index + 1}`}
          maxLength={1}
          className={cn(
            "mono h-[3.25rem] w-full min-w-0 rounded-xl border border-line bg-surface text-center",
            "text-lg font-semibold text-ink shadow-subtle outline-none transition-all",
            "focus:border-brand focus:ring-4 focus:ring-brand/12",
            "disabled:cursor-not-allowed disabled:bg-elevated disabled:opacity-60",
          )}
        />
      ))}
    </div>
  );
}

/** "Resend code" with the cooldown the backend enforces, shown as a countdown. */
export function ResendButton({
  cooldownSeconds,
  onResend,
  disabled,
}: {
  cooldownSeconds: number;
  onResend: () => Promise<void>;
  disabled?: boolean;
}) {
  const [remaining, setRemaining] = React.useState(0);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (remaining <= 0) return;
    const timer = setTimeout(() => setRemaining((value) => value - 1), 1000);
    return () => clearTimeout(timer);
  }, [remaining]);

  const click = async () => {
    setBusy(true);
    try {
      await onResend();
      setRemaining(cooldownSeconds);
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={click}
      disabled={busy || disabled || remaining > 0}
      className="text-xs font-semibold text-brand-ink transition-colors hover:underline disabled:cursor-not-allowed disabled:text-faint disabled:no-underline"
    >
      {remaining > 0 ? `Resend code in ${remaining}s` : busy ? "Sending…" : "Resend code"}
    </button>
  );
}
