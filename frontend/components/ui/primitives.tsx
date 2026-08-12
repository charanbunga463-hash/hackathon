"use client";

import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/* --------------------------------------------------------------- Button -- */

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-accent text-white hover:bg-accent/90",
        secondary: "border border-line bg-elevated text-ink hover:bg-line/40",
        ghost: "text-muted hover:bg-elevated hover:text-ink",
        danger: "bg-danger text-white hover:bg-danger/90",
        success: "bg-ok text-white hover:bg-ok/90",
        outline: "border border-line bg-transparent text-ink hover:bg-elevated",
      },
      size: {
        sm: "h-7 px-2.5 text-xs",
        md: "h-9 px-3.5",
        lg: "h-10 px-5",
        icon: "h-8 w-8",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading, children, disabled, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
      {children}
    </button>
  ),
);
Button.displayName = "Button";

/* ---------------------------------------------------------------- Badge -- */

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-2xs font-medium",
  {
    variants: {
      tone: {
        ok: "border-ok/30 bg-ok/10 text-ok",
        warn: "border-warn/30 bg-warn/10 text-warn",
        danger: "border-danger/30 bg-danger/10 text-danger",
        info: "border-info/30 bg-info/10 text-info",
        accent: "border-accent/30 bg-accent/10 text-accent",
        muted: "border-line bg-elevated text-muted",
      },
    },
    defaultVariants: { tone: "muted" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

/* ---------------------------------------------------------------- Panel -- */

export function Panel({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("panel", className)} {...props}>
      {children}
    </div>
  );
}

export function PanelHeader({
  title,
  subtitle,
  icon,
  actions,
  className,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("panel-header", className)}>
      <div className="flex min-w-0 items-center gap-2.5">
        {icon ? <span className="shrink-0 text-muted">{icon}</span> : null}
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>
          {subtitle ? (
            <p className="truncate text-xs text-muted">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/* ------------------------------------------------------------- Feedback -- */

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin text-muted", className)} aria-hidden />;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 px-6 py-14 text-center", className)}>
      {icon ? <div className="text-faint">{icon}</div> : null}
      <div className="space-y-1">
        <p className="text-sm font-medium text-ink">{title}</p>
        {description ? (
          <p className="mx-auto max-w-md text-xs leading-relaxed text-muted">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function ErrorNote({ message, className }: { message: string; className?: string }) {
  return (
    <div
      className={cn(
        "rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger",
        className,
      )}
      role="alert"
    >
      {message}
    </div>
  );
}

/* --------------------------------------------------------------- Inputs -- */

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-9 w-full rounded-md border border-line bg-canvas px-3 text-sm text-ink placeholder:text-faint",
        "focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/40",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

/* ---------------------------------------------------------------- Misc --- */

export function StatTile({
  label,
  value,
  hint,
  icon,
  tone = "muted",
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ReactNode;
  tone?: "ok" | "warn" | "danger" | "accent" | "muted";
}) {
  const toneClass = {
    ok: "text-ok",
    warn: "text-warn",
    danger: "text-danger",
    accent: "text-accent",
    muted: "text-ink",
  }[tone];

  return (
    <div className="panel p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
        {icon ? <span className="text-faint">{icon}</span> : null}
      </div>
      <p className={cn("mt-2 text-2xl font-semibold tabular-nums", toneClass)}>{value}</p>
      {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

export function KeyValue({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5 text-xs">
      <span className="shrink-0 text-muted">{label}</span>
      <span className="min-w-0 text-right text-ink">{children}</span>
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
  className,
}: {
  tabs: { id: T; label: string; count?: number }[];
  active: T;
  onChange: (id: T) => void;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-1 border-b border-line", className)} role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            "-mb-px border-b-2 px-3 py-2 text-xs font-medium transition-colors",
            active === tab.id
              ? "border-accent text-ink"
              : "border-transparent text-muted hover:text-ink",
          )}
        >
          {tab.label}
          {typeof tab.count === "number" ? (
            <span className="ml-1.5 rounded bg-elevated px-1.5 py-0.5 text-2xs tabular-nums text-muted">
              {tab.count}
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

export function Progress({ value, tone = "accent" }: { value: number; tone?: "accent" | "ok" | "danger" }) {
  const toneClass = { accent: "bg-accent", ok: "bg-ok", danger: "bg-danger" }[tone];
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-elevated">
      <div
        className={cn("h-full rounded-full transition-all", toneClass)}
        style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }}
      />
    </div>
  );
}

/* ----------------------------------------------------------- Page shell -- */

/**
 * The one page heading. Every top-level page uses it, so the title, the
 * supporting line and the primary action sit in the same place on all of them.
 */
export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 space-y-1">
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {description ? (
          <p className="max-w-2xl text-sm text-muted">{description}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}

/**
 * One titled block of a settings-style page.
 *
 * `tone="danger"` is not decoration: it is the visual contract that everything
 * inside is irreversible, so a destructive control can never be mistaken for an
 * ordinary one.
 */
export function Section({
  title,
  description,
  tone = "default",
  children,
}: {
  title: string;
  description?: React.ReactNode;
  tone?: "default" | "danger";
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "rounded-lg border bg-surface",
        tone === "danger" ? "border-danger/40" : "border-line",
      )}
    >
      <div
        className={cn(
          "border-b px-4 py-3 sm:px-5",
          tone === "danger" ? "border-danger/30 bg-danger/5" : "border-line",
        )}
      >
        <h2
          className={cn(
            "text-sm font-semibold",
            tone === "danger" ? "text-danger" : "text-ink",
          )}
        >
          {title}
        </h2>
        {description ? (
          <p className="mt-0.5 text-xs text-muted">{description}</p>
        ) : null}
      </div>
      <div className="divide-y divide-line">{children}</div>
    </section>
  );
}

/**
 * One labelled row inside a Section.
 *
 * Stacks on narrow screens rather than letting a control squeeze itself off the
 * edge of its card — the failure mode this layout exists to prevent.
 */
export function SettingRow({
  label,
  hint,
  control,
  children,
}: {
  label: string;
  hint?: React.ReactNode;
  control?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="px-4 py-3.5 sm:px-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 space-y-0.5">
          <p className="text-sm font-medium text-ink">{label}</p>
          {hint ? <p className="text-xs leading-relaxed text-muted">{hint}</p> : null}
        </div>
        {control ? (
          <div className="w-full shrink-0 sm:w-auto sm:max-w-xs">{control}</div>
        ) : null}
      </div>
      {children ? <div className="mt-3">{children}</div> : null}
    </div>
  );
}

/* --------------------------------------------------------------- Fields -- */

export function Field({
  label,
  error,
  hint,
  htmlFor,
  children,
}: {
  label: string;
  error?: string | null;
  hint?: React.ReactNode;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-muted">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-faint">{hint}</p>
      ) : null}
    </div>
  );
}

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...props }, ref) => (
  <select
    ref={ref}
    className={cn(
      "h-9 w-full rounded-md border border-line bg-canvas px-2.5 text-sm text-ink",
      "focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent/40",
      className,
    )}
    {...props}
  >
    {children}
  </select>
));
Select.displayName = "Select";

/** An on/off control. Labelled by its SettingRow, so it needs no text of its own. */
export function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
        checked ? "bg-accent" : "bg-line",
        disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
      )}
    >
      <span
        className={cn(
          "inline-block h-4.5 w-4.5 transform rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-6" : "translate-x-1",
        )}
      />
    </button>
  );
}

/* --------------------------------------------------------------- Alerts -- */

export function Alert({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: "ok" | "warn" | "danger" | "info";
  title?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  const toneClass = {
    ok: "border-ok/30 bg-ok/10 text-ok",
    warn: "border-warn/30 bg-warn/10 text-warn",
    danger: "border-danger/30 bg-danger/10 text-danger",
    info: "border-info/30 bg-info/10 text-info",
  }[tone];
  return (
    <div
      className={cn("rounded-md border px-3 py-2.5 text-xs leading-relaxed", toneClass, className)}
      role={tone === "danger" ? "alert" : "status"}
    >
      {title ? <p className="font-medium">{title}</p> : null}
      {children ? <div className={title ? "mt-1 opacity-90" : ""}>{children}</div> : null}
    </div>
  );
}

/* ---------------------------------------------------------------- Modal -- */

/**
 * A confirmation the user has to mean.
 *
 * Replaces `window.confirm` for destructive actions: `confirmText` makes the
 * user type the thing being destroyed, so a mis-click cannot delete an account
 * or a project. Closes on Escape and on a backdrop click.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  confirmText,
  tone = "danger",
  busy,
  error,
  extra,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: React.ReactNode;
  confirmLabel?: string;
  /** When set, the confirm button stays disabled until the user types this. */
  confirmText?: string;
  tone?: "danger" | "primary";
  busy?: boolean;
  error?: string | null;
  /** Extra inputs (e.g. a password) rendered above the buttons. */
  extra?: React.ReactNode;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [typed, setTyped] = React.useState("");

  React.useEffect(() => {
    if (!open) setTyped("");
  }, [open]);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, busy, onCancel]);

  if (!open) return null;

  const ready = !confirmText || typed.trim() === confirmText;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-4 sm:items-center"
      onClick={() => !busy && onCancel()}
      role="presentation"
    >
      <div
        className="w-full max-w-md rounded-lg border border-line bg-surface shadow-xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="space-y-2 px-5 py-4">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          <div className="text-xs leading-relaxed text-muted">{description}</div>
        </div>

        {(confirmText || extra) ? (
          <div className="space-y-3 border-t border-line px-5 py-4">
            {extra}
            {confirmText ? (
              <Field label={`Type "${confirmText}" to confirm`}>
                <Input
                  value={typed}
                  onChange={(event) => setTyped(event.target.value)}
                  autoComplete="off"
                  aria-label={`Type ${confirmText} to confirm`}
                />
              </Field>
            ) : null}
          </div>
        ) : null}

        {error ? (
          <div className="px-5 pb-1">
            <ErrorNote message={error} />
          </div>
        ) : null}

        <div className="flex flex-col-reverse gap-2 border-t border-line px-5 py-3 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : "primary"}
            onClick={onConfirm}
            loading={busy}
            disabled={!ready}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
