"use client";

/**
 * The Daylight component library.
 *
 * Every visual decision the app makes lives in this file. Pages compose these
 * and never reach for a raw colour, radius or shadow of their own — that is
 * what keeps eleven screens looking like one product.
 *
 * The rules encoded here:
 *
 *   * Tone is semantic, never decorative. `ok` means a real pass, `danger`
 *     means a real failure. A component picks a tone from what happened.
 *   * Text on a tinted surface always uses the matching `-ink` token, so a
 *     warning is readable rather than merely yellow.
 *   * Depth means interactivity. A raised, lifting surface can be clicked; a
 *     sunken `tile` cannot.
 */

import { cva, type VariantProps } from "class-variance-authority";
import { Loader2, X } from "lucide-react";
import * as React from "react";

import { cn, type Tone } from "@/lib/utils";

/* ============================================================== tones ===== */

export type { Tone };

/** Pale surface + matching border + readable text, for every semantic tone. */
export const TONE_SOFT: Record<Tone, string> = {
  ok: "border-ok-line bg-ok-soft text-ok-ink",
  warn: "border-warn-line bg-warn-soft text-warn-ink",
  danger: "border-danger-line bg-danger-soft text-danger-ink",
  info: "border-info-line bg-info-soft text-info-ink",
  brand: "border-brand-line bg-brand-soft text-brand-ink",
  grape: "border-grape-line bg-grape-soft text-grape-ink",
  muted: "border-line bg-elevated text-muted",
};

/** The saturated hue, for dots, bars and icons. */
export const TONE_SOLID: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  info: "bg-info",
  brand: "bg-brand",
  grape: "bg-grape",
  muted: "bg-faint",
};

/** Readable text of a tone on a white surface. */
export const TONE_TEXT: Record<Tone, string> = {
  ok: "text-ok-ink",
  warn: "text-warn-ink",
  danger: "text-danger-ink",
  info: "text-info-ink",
  brand: "text-brand-ink",
  grape: "text-grape-ink",
  muted: "text-muted",
};

/* ============================================================= button ===== */

const buttonVariants = cva(
  cn(
    "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-lg",
    "font-medium transition-all duration-200",
    "disabled:pointer-events-none disabled:opacity-50",
  ),
  {
    variants: {
      variant: {
        /** The one action a screen most wants you to take. */
        primary:
          "bg-brand-gradient text-white shadow-glow hover:-translate-y-px hover:shadow-glow-lg active:translate-y-0",
        /** The default. White paper, quiet until you touch it. */
        secondary:
          "border border-line bg-surface text-ink shadow-subtle hover:border-brand-line hover:bg-brand-soft hover:text-brand-ink",
        /** A tinted, low-weight call to action. */
        soft: "border border-brand-line bg-brand-soft text-brand-ink hover:bg-brand-line/60",
        ghost: "text-muted hover:bg-elevated hover:text-ink",
        outline: "border border-line-strong bg-transparent text-ink hover:bg-elevated",
        danger:
          "bg-danger text-white shadow-[0_8px_20px_-8px_rgb(var(--danger)/0.5)] hover:-translate-y-px hover:bg-danger-ink",
        success:
          "bg-ok text-white shadow-[0_8px_20px_-8px_rgb(var(--ok)/0.5)] hover:-translate-y-px hover:bg-ok-ink",
      },
      size: {
        xs: "h-7 px-2.5 text-2xs",
        sm: "h-8 px-3 text-xs",
        md: "h-9.5 px-4 text-sm",
        lg: "h-11 px-6 text-sm",
        icon: "h-8 w-8",
        "icon-lg": "h-9.5 w-9.5",
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

/** A link that has to look like a Button. Same classes, anchor semantics. */
export function LinkButton({
  className,
  variant,
  size,
  children,
  ...props
}: React.AnchorHTMLAttributes<HTMLAnchorElement> & VariantProps<typeof buttonVariants>) {
  return (
    <a className={cn(buttonVariants({ variant, size }), className)} {...props}>
      {children}
    </a>
  );
}

/* ============================================================== badge ===== */

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function Badge({ className, tone = "muted", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-semibold",
        TONE_SOFT[tone],
        className,
      )}
      {...props}
    />
  );
}

/** A live status pip. `pulse` only when something is genuinely in flight. */
export function StatusDot({
  tone = "muted",
  pulse,
  className,
}: {
  tone?: Tone;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("relative flex h-2 w-2 shrink-0", className)} aria-hidden>
      {pulse ? (
        <span
          className={cn(
            "absolute inline-flex h-full w-full animate-ping rounded-full opacity-60",
            TONE_SOLID[tone],
          )}
        />
      ) : null}
      <span className={cn("relative inline-flex h-2 w-2 rounded-full", TONE_SOLID[tone])} />
    </span>
  );
}

/** The square, tinted icon holder used in headers and feature rows. */
export function IconTile({
  tone = "brand",
  size = "md",
  children,
  className,
}: {
  tone?: Tone;
  size?: "sm" | "md" | "lg";
  children: React.ReactNode;
  className?: string;
}) {
  const box = { sm: "h-7 w-7 rounded-lg", md: "h-9 w-9 rounded-xl", lg: "h-11 w-11 rounded-2xl" }[
    size
  ];
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center border",
        box,
        TONE_SOFT[tone],
        className,
      )}
      aria-hidden
    >
      {children}
    </span>
  );
}

/* =============================================================== card ===== */

export function Card({
  className,
  interactive,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      className={cn("card", interactive && "card-interactive", className)}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({
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
    <div className={cn("card-header", className)}>
      <div className="flex min-w-0 items-center gap-2.5">
        {icon}
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>
          {subtitle ? <p className="truncate text-xs text-muted">{subtitle}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/* Names the rest of the app grew up with, pointed at the new components. */
export const Panel = Card;
export const PanelHeader = CardHeader;

/* =========================================================== feedback ===== */

export function Spinner({ className }: { className?: string }) {
  return (
    <Loader2 className={cn("h-4 w-4 animate-spin text-brand", className)} aria-hidden />
  );
}

/** A centred, honest "there is nothing here yet, and here is what to do". */
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
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-6 py-12 text-center",
        className,
      )}
    >
      {icon ? (
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-brand-line bg-brand-soft text-brand">
          {icon}
        </span>
      ) : null}
      <div className="space-y-1">
        <p className="text-sm font-semibold text-ink">{title}</p>
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
        "rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-xs font-medium text-danger-ink",
        className,
      )}
      role="alert"
    >
      {message}
    </div>
  );
}

export function Alert({
  tone = "info",
  title,
  icon,
  children,
  className,
}: {
  tone?: Tone;
  title?: React.ReactNode;
  icon?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex gap-2.5 rounded-xl border px-3.5 py-3 text-xs leading-relaxed",
        TONE_SOFT[tone],
        className,
      )}
      role={tone === "danger" ? "alert" : "status"}
    >
      {icon ? <span className="mt-px shrink-0">{icon}</span> : null}
      <div className="min-w-0">
        {title ? <p className="font-semibold">{title}</p> : null}
        {children ? <div className={title ? "mt-1 opacity-90" : ""}>{children}</div> : null}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden />;
}

/** The standard "we are fetching" block, so every page waits the same way. */
export function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="card flex items-center justify-center gap-2.5 py-16">
      <Spinner className="h-5 w-5" />
      <span className="text-sm text-muted">{label}</span>
    </div>
  );
}

/* ============================================================= inputs ===== */

const fieldBase = cn(
  "w-full rounded-lg border border-line bg-surface text-sm text-ink shadow-subtle",
  "placeholder:text-faint transition-colors",
  "hover:border-line-strong",
  "focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/12",
  "disabled:cursor-not-allowed disabled:bg-elevated disabled:text-muted",
);

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }
>(({ className, invalid, ...props }, ref) => (
  <input
    ref={ref}
    aria-invalid={invalid || undefined}
    className={cn(
      fieldBase,
      "h-9.5 px-3",
      invalid && "border-danger focus:border-danger focus:ring-danger/15",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(fieldBase, "min-h-[5rem] px-3 py-2", className)} {...props} />
));
Textarea.displayName = "Textarea";

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...props }, ref) => (
  <select ref={ref} className={cn(fieldBase, "h-9.5 px-2.5", className)} {...props}>
    {children}
  </select>
));
Select.displayName = "Select";

export function Field({
  label,
  error,
  hint,
  htmlFor,
  children,
}: {
  label: React.ReactNode;
  error?: string | null;
  hint?: React.ReactNode;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-semibold text-ink">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-xs font-medium text-danger-ink" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs leading-relaxed text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

/** An on/off control. Labelled by its row, so it carries no text of its own. */
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
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors duration-200",
        checked ? "bg-brand shadow-glow" : "bg-line-strong",
        disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
      )}
    >
      <span
        className={cn(
          "inline-block h-[1.125rem] w-[1.125rem] transform rounded-full bg-white shadow-subtle transition-transform duration-200",
          checked ? "translate-x-[1.4rem]" : "translate-x-[0.2rem]",
        )}
      />
    </button>
  );
}

/* =============================================================== nav ====== */

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
  className,
}: {
  tabs: { id: T; label: string; count?: number; icon?: React.ReactNode }[];
  active: T;
  onChange: (id: T) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      className={cn(
        "scroll-thin flex items-center gap-1 overflow-x-auto rounded-xl border border-line bg-surface p-1 shadow-subtle",
        className,
      )}
    >
      {tabs.map((tab) => {
        const selected = active === tab.id;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(tab.id)}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all duration-200",
              selected
                ? "bg-brand-gradient text-white shadow-glow"
                : "text-muted hover:bg-elevated hover:text-ink",
            )}
          >
            {tab.icon}
            {tab.label}
            {typeof tab.count === "number" ? (
              <span
                className={cn(
                  "rounded-full px-1.5 py-px text-2xs tabular-nums",
                  selected ? "bg-white/25 text-white" : "bg-elevated text-muted",
                )}
              >
                {tab.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export function Progress({
  value,
  tone = "brand",
  className,
}: {
  /** 0–1. */
  value: number;
  tone?: Tone;
  className?: string;
}) {
  return (
    <div className={cn("h-2 w-full overflow-hidden rounded-full bg-elevated", className)}>
      <div
        className={cn("h-full rounded-full transition-[width] duration-500", TONE_SOLID[tone])}
        style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }}
      />
    </div>
  );
}

/* ============================================================== stats ===== */

/**
 * One headline number. The tone colours the value, never the whole card — a
 * wall of tinted cards stops meaning anything.
 */
export function StatTile({
  label,
  value,
  hint,
  icon,
  tone = "brand",
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <div className={cn("card card-interactive relative overflow-hidden p-4", className)}>
      {/* A hairline of the tone across the top: colour you can scan without
          tinting the surface the number sits on. */}
      <span
        aria-hidden
        className={cn("absolute inset-x-0 top-0 h-0.5", TONE_SOLID[tone])}
      />
      <div className="flex items-start justify-between gap-3">
        <p className="text-2xs font-semibold uppercase tracking-wider text-muted">{label}</p>
        {icon ? <IconTile tone={tone} size="sm">{icon}</IconTile> : null}
      </div>
      <div className={cn("mt-3 text-2xl font-bold tabular-nums tracking-tight", TONE_TEXT[tone])}>
        {value}
      </div>
      {hint ? <div className="mt-1.5 text-xs text-muted">{hint}</div> : null}
    </div>
  );
}

export function KeyValue({
  label,
  children,
  mono,
}: {
  label: string;
  children: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line py-2 text-xs last:border-0">
      <span className="shrink-0 font-medium text-muted">{label}</span>
      <span className={cn("min-w-0 truncate text-right text-ink", mono && "mono")}>
        {children}
      </span>
    </div>
  );
}

/* ========================================================= page shell ===== */

/** The one page heading, so every screen starts in the same place. */
export function PageHeader({
  title,
  description,
  eyebrow,
  action,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  eyebrow?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between",
        className,
      )}
    >
      <div className="min-w-0 space-y-1.5">
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1 className="text-2xl font-bold tracking-tight text-ink">{title}</h1>
        {description ? (
          <p className="max-w-2xl text-sm leading-relaxed text-muted">{description}</p>
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
 * inside is irreversible, so a destructive control can never be mistaken for
 * an ordinary one.
 */
export function Section({
  title,
  description,
  icon,
  tone = "default",
  children,
}: {
  title: string;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  tone?: "default" | "danger";
  children: React.ReactNode;
}) {
  const danger = tone === "danger";
  return (
    <section
      className={cn(
        "overflow-hidden rounded-card border bg-surface shadow-card",
        danger ? "border-danger-line" : "border-line",
      )}
    >
      <div
        className={cn(
          "flex items-center gap-3 border-b px-4 py-3.5 sm:px-5",
          danger ? "border-danger-line bg-danger-soft" : "border-line bg-elevated/60",
        )}
      >
        {icon ? <IconTile tone={danger ? "danger" : "brand"} size="sm">{icon}</IconTile> : null}
        <div className="min-w-0">
          <h2
            className={cn(
              "text-sm font-semibold",
              danger ? "text-danger-ink" : "text-ink",
            )}
          >
            {title}
          </h2>
          {description ? (
            <p className="mt-0.5 text-xs text-muted">{description}</p>
          ) : null}
        </div>
      </div>
      <div className="divide-y divide-line">{children}</div>
    </section>
  );
}

/**
 * One labelled row inside a Section. Stacks on narrow screens rather than
 * letting a control squeeze itself off the edge of its card.
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
    <div className="px-4 py-4 sm:px-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 space-y-0.5">
          <p className="text-sm font-semibold text-ink">{label}</p>
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

/* ============================================================== modal ===== */

/**
 * The one dialog shell. Closes on Escape and on a backdrop click, traps the
 * page behind a light scrim rather than a black one, and never closes while
 * `busy` — a half-finished upload must not be dismissed by a stray click.
 */
export function Modal({
  open,
  onClose,
  title,
  description,
  icon,
  busy,
  footer,
  children,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  busy?: boolean;
  footer?: React.ReactNode;
  children?: React.ReactNode;
  size?: "sm" | "md" | "lg";
}) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  const width = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" }[size];

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-ink/25 p-4 backdrop-blur-sm animate-fade-in sm:items-center"
      onClick={() => !busy && onClose()}
      role="presentation"
    >
      <div
        onClick={(event) => event.stopPropagation()}
        className={cn(
          "w-full overflow-hidden rounded-2xl border border-line bg-surface shadow-pop animate-scale-in",
          width,
        )}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex items-start gap-3 border-b border-line px-5 py-4">
          {icon}
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold text-ink">{title}</h2>
            {description ? (
              <div className="mt-0.5 text-xs leading-relaxed text-muted">{description}</div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
            className="-mr-1 -mt-1 rounded-lg p-1.5 text-faint transition-colors hover:bg-elevated hover:text-ink disabled:opacity-50"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {children ? <div className="px-5 py-4">{children}</div> : null}

        {footer ? (
          <div className="flex flex-col-reverse gap-2 border-t border-line bg-elevated/50 px-5 py-3.5 sm:flex-row sm:justify-end">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * A confirmation the user has to mean.
 *
 * `confirmText` makes them type the thing being destroyed, so a mis-click
 * cannot delete an account or a project.
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

  const ready = !confirmText || typed.trim() === confirmText;

  return (
    <Modal
      open={open}
      onClose={onCancel}
      busy={busy}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
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
        </>
      }
    >
      {extra || confirmText || error ? (
        <div className="space-y-3">
          {extra}
          {confirmText ? (
            <Field label={`Type “${confirmText}” to confirm`}>
              <Input
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                autoComplete="off"
                aria-label={`Type ${confirmText} to confirm`}
              />
            </Field>
          ) : null}
          {error ? <ErrorNote message={error} /> : null}
        </div>
      ) : null}
    </Modal>
  );
}
