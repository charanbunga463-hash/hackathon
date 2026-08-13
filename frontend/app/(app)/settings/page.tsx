"use client";

/**
 * Settings.
 *
 * The rule this page is built on: every control here changes something. Each
 * one maps to an endpoint under `/api/account`, and each preference is read by
 * named backend code (see `UserPreferences` in backend/app/models/user.py). The
 * read-only facts about how the instance is deployed sit at the bottom, clearly
 * labelled as configuration the user cannot change — not mixed in with things
 * they can.
 *
 * There is no appearance section: the product ships one theme, so a control
 * that only ever had one sensible value would be a control that lies.
 */

import {
  Cpu,
  KeyRound,
  Monitor,
  ShieldCheck,
  Trash2,
  User as UserIcon,
} from "lucide-react";
import * as React from "react";

import { useAuth } from "@/components/auth/auth-context";
import {
  Alert,
  Badge,
  Button,
  ConfirmDialog,
  ErrorNote,
  Field,
  Input,
  PageHeader,
  Section,
  SettingRow,
  Spinner,
  Toggle,
} from "@/components/ui/primitives";
import { useAsync } from "@/hooks/useEvents";
import {
  changePassword,
  deleteAccount,
  getSystem,
  listActiveSessions,
  revokeAllSessions,
  updatePreferences,
  updateProfile,
} from "@/lib/api";
import { errorField, errorMessage, validateName, validatePassword } from "@/lib/auth";
import { formatRelative } from "@/lib/utils";
import type { UserPreferences } from "@/types";

export default function SettingsPage() {
  const { user, loading, refresh, signOut } = useAuth();

  if (loading || !user) {
    return (
      <div className="flex items-center justify-center gap-2.5 py-24">
        <Spinner className="h-5 w-5" />
        <span className="text-sm text-muted">Loading settings…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-up">
      <PageHeader
        eyebrow="Account"
        title="Settings"
        description="Your account, your security, and how API Doctor behaves when it tests your APIs."
      />

      <AccountSection onSaved={refresh} />
      <SecuritySection onSignedOut={signOut} />
      <BehaviourSection preferences={user.preferences} onSaved={refresh} />
      <InstanceSection />
      <DangerSection onDeleted={signOut} />
    </div>
  );
}

/* --------------------------------------------------------------- Account -- */

function AccountSection({ onSaved }: { onSaved: () => Promise<void> }) {
  const { user } = useAuth();
  const [name, setName] = React.useState(user?.name ?? "");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState(false);

  React.useEffect(() => {
    setName(user?.name ?? "");
  }, [user?.name]);

  const dirty = name.trim() !== (user?.name ?? "").trim();

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    const problem = validateName(name);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await updateProfile(name.trim());
      await onSaved();
      setSaved(true);
    } catch (exc) {
      setError(errorMessage(exc, "Could not save your name."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section
      title="Account"
      description="Who you are on this instance."
      icon={<UserIcon className="h-3.5 w-3.5" />}
    >
      <div className="px-4 py-4 sm:px-5">
        <form onSubmit={save} className="max-w-md space-y-4">
          <Field label="Name" error={error} htmlFor="settings-name">
            <Input
              id="settings-name"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setSaved(false);
              }}
              maxLength={80}
              autoComplete="name"
            />
          </Field>

          <Field
            label="Email"
            htmlFor="settings-email"
            hint="Your email address is your sign-in identity and cannot be changed here."
          >
            <Input id="settings-email" value={user?.email ?? ""} disabled readOnly />
          </Field>

          <div className="flex items-center gap-3">
            <Button type="submit" variant="primary" loading={busy} disabled={!dirty}>
              {busy ? "Saving…" : "Save changes"}
            </Button>
            {saved && !dirty ? (
              <span className="text-xs font-semibold text-ok-ink">Saved.</span>
            ) : null}
          </div>
        </form>
      </div>

      <PasswordRow />
    </Section>
  );
}

function PasswordRow() {
  const [open, setOpen] = React.useState(false);
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [field, setField] = React.useState<string | null>(null);
  const [done, setDone] = React.useState<string | null>(null);

  const reset = () => {
    setCurrent("");
    setNext("");
    setConfirm("");
    setError(null);
    setField(null);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setError(null);
    setField(null);

    if (next !== confirm) {
      setField("confirm");
      setError("Those passwords do not match.");
      return;
    }
    const problem = validatePassword(next);
    if (problem) {
      setField("new_password");
      setError(problem);
      return;
    }

    setBusy(true);
    try {
      const result = await changePassword(current, next);
      setDone(result.detail);
      setOpen(false);
      reset();
    } catch (exc) {
      setField(errorField(exc));
      setError(errorMessage(exc, "Could not change your password."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SettingRow
      label="Password"
      hint="Changing it signs out every other device."
      control={
        !open ? (
          <Button
            variant="secondary"
            className="w-full sm:w-auto"
            onClick={() => {
              setDone(null);
              setOpen(true);
            }}
          >
            <KeyRound className="h-4 w-4" />
            Change password
          </Button>
        ) : null
      }
    >
      {done ? <Alert tone="ok">{done}</Alert> : null}

      {open ? (
        <form onSubmit={submit} className="max-w-md space-y-4">
          <Field
            label="Current password"
            htmlFor="pw-current"
            error={field === "current_password" ? error : null}
          >
            <Input
              id="pw-current"
              type="password"
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>

          <Field
            label="New password"
            htmlFor="pw-new"
            error={field === "new_password" ? error : null}
            hint="At least 10 characters, with a letter and a number."
          >
            <Input
              id="pw-new"
              type="password"
              value={next}
              onChange={(event) => setNext(event.target.value)}
              autoComplete="new-password"
              required
            />
          </Field>

          <Field
            label="Confirm new password"
            htmlFor="pw-confirm"
            error={field === "confirm" ? error : null}
          >
            <Input
              id="pw-confirm"
              type="password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              autoComplete="new-password"
              required
            />
          </Field>

          {error && !field ? <ErrorNote message={error} /> : null}

          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            <Button
              type="button"
              variant="secondary"
              disabled={busy}
              onClick={() => {
                setOpen(false);
                reset();
              }}
            >
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={busy}>
              {busy ? "Updating…" : "Update password"}
            </Button>
          </div>
        </form>
      ) : null}
    </SettingRow>
  );
}

/* -------------------------------------------------------------- Security -- */

function SecuritySection({ onSignedOut }: { onSignedOut: () => Promise<void> }) {
  const { user } = useAuth();
  const { data, loading, error, refresh } = useAsync(listActiveSessions, []);
  const [confirming, setConfirming] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [failure, setFailure] = React.useState<string | null>(null);

  const revoke = async () => {
    setBusy(true);
    setFailure(null);
    try {
      await revokeAllSessions();
      // This session was revoked too, so the only correct next state is the
      // sign-in page.
      await onSignedOut();
    } catch (exc) {
      setFailure(errorMessage(exc, "Could not sign out your sessions."));
      setBusy(false);
    }
  };

  return (
    <Section
      title="Security"
      description="Verification status and where you are signed in."
      icon={<ShieldCheck className="h-3.5 w-3.5" />}
    >
      <SettingRow
        label="Email verification"
        hint={user?.email}
        control={
          user?.email_verified ? (
            <Badge tone="ok">Verified</Badge>
          ) : (
            <Badge tone="warn">Not verified</Badge>
          )
        }
      />

      <SettingRow
        label="Active sessions"
        hint="Every browser or device currently signed in to this account."
      >
        {loading && !data ? (
          <p className="flex items-center gap-2 text-xs text-muted">
            <Spinner className="h-3.5 w-3.5" /> Loading sessions…
          </p>
        ) : error ? (
          <ErrorNote message={error} />
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line">
            {(data?.sessions ?? []).map((session) => (
              <li
                key={session.id}
                className="flex flex-col gap-1 bg-sunken px-3.5 py-2.5 text-xs sm:flex-row sm:items-center sm:justify-between"
              >
                <span className="min-w-0">
                  <span
                    className="block truncate font-medium text-ink"
                    title={session.user_agent}
                  >
                    {describeAgent(session.user_agent)}
                  </span>
                  <span className="block text-2xs text-faint">
                    Last active{" "}
                    {formatRelative(new Date(session.last_seen * 1000).toISOString())}
                  </span>
                </span>
                {session.current ? <Badge tone="brand">This device</Badge> : null}
              </li>
            ))}
          </ul>
        )}

        {failure ? <ErrorNote className="mt-3" message={failure} /> : null}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button variant="danger" size="sm" onClick={() => setConfirming(true)}>
            Log out all sessions
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void refresh()}>
            Refresh
          </Button>
        </div>
      </SettingRow>

      <ConfirmDialog
        open={confirming}
        title="Sign out everywhere?"
        description="Every device signed in to this account will be signed out, including this one. You will need to sign in again."
        confirmLabel="Log out all sessions"
        busy={busy}
        onConfirm={revoke}
        onCancel={() => setConfirming(false)}
      />
    </Section>
  );
}

/** Turn a raw user-agent into something a person can recognise. */
function describeAgent(agent: string): string {
  if (!agent) return "Unknown device";
  const browser = /Edg\//.test(agent)
    ? "Edge"
    : /OPR\//.test(agent)
      ? "Opera"
      : /Chrome\//.test(agent)
        ? "Chrome"
        : /Safari\//.test(agent)
          ? "Safari"
          : /Firefox\//.test(agent)
            ? "Firefox"
            : null;
  const platform = /Windows/.test(agent)
    ? "Windows"
    : /Macintosh|Mac OS/.test(agent)
      ? "macOS"
      : /Android/.test(agent)
        ? "Android"
        : /iPhone|iPad/.test(agent)
          ? "iOS"
          : /Linux/.test(agent)
            ? "Linux"
            : null;
  if (browser && platform) return `${browser} on ${platform}`;
  return browser ?? platform ?? agent.slice(0, 60);
}

/* ------------------------------------------------------------- Behaviour -- */

/**
 * A preference control that saves on change and rolls back if the save fails.
 * Optimistic without lying: a rejected change does not stay on screen.
 */
function usePreferenceSaver(onSaved: () => Promise<void>) {
  const [saving, setSaving] = React.useState<keyof UserPreferences | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const save = React.useCallback(
    async (changes: Partial<UserPreferences>) => {
      const key = Object.keys(changes)[0] as keyof UserPreferences;
      setSaving(key);
      setError(null);
      try {
        await updatePreferences(changes);
        await onSaved();
      } catch (exc) {
        setError(errorMessage(exc, "Could not save that preference."));
        // Re-read so the control shows what is actually stored.
        await onSaved();
      } finally {
        setSaving(null);
      }
    },
    [onSaved],
  );

  return { save, saving, error };
}

function BehaviourSection({
  preferences,
  onSaved,
}: {
  preferences: UserPreferences;
  onSaved: () => Promise<void>;
}) {
  const { save, saving, error } = usePreferenceSaver(onSaved);
  const [timeout, setTimeoutValue] = React.useState(String(preferences.api_timeout_seconds));

  React.useEffect(() => {
    setTimeoutValue(String(preferences.api_timeout_seconds));
  }, [preferences.api_timeout_seconds]);

  const timeoutDirty = Number(timeout) !== preferences.api_timeout_seconds;

  return (
    <Section
      title="API Doctor"
      description="How your APIs are tested and analysed. These apply to every run you start."
      icon={<Monitor className="h-3.5 w-3.5" />}
    >
      {error ? (
        <div className="px-4 pt-3 sm:px-5">
          <ErrorNote message={error} />
        </div>
      ) : null}

      <SettingRow
        label="Request timeout"
        hint="How long each endpoint is given to respond before the call is recorded as a timeout. 1–300 seconds."
        control={
          <div className="flex items-center gap-2">
            <Input
              type="number"
              min={1}
              max={300}
              value={timeout}
              aria-label="Request timeout in seconds"
              onChange={(event) => setTimeoutValue(event.target.value)}
              className="w-24"
            />
            <span className="text-xs text-muted">sec</span>
            <Button
              variant="secondary"
              size="sm"
              disabled={!timeoutDirty}
              loading={saving === "api_timeout_seconds"}
              onClick={() => {
                const value = Math.max(1, Math.min(300, Number(timeout) || 30));
                setTimeoutValue(String(value));
                void save({ api_timeout_seconds: value });
              }}
            >
              Save
            </Button>
          </div>
        }
      />

      <SettingRow
        label="Test write endpoints"
        hint="Call POST, PUT, PATCH and DELETE routes during a test run. Off by default — your project's data store is real, and these requests change it."
        control={
          <Toggle
            label="Test write endpoints"
            checked={preferences.probe_write_methods}
            disabled={saving === "probe_write_methods"}
            onChange={(value) => void save({ probe_write_methods: value })}
          />
        }
      />

      <SettingRow
        label="AI analysis"
        hint="Use the AI model to explain failures and propose fixes. When off, results come from the deterministic rule engine only and no model is called — status codes, timings and test results are measured either way."
        control={
          <Toggle
            label="AI analysis"
            checked={preferences.ai_analysis}
            disabled={saving === "ai_analysis"}
            onChange={(value) => void save({ ai_analysis: value })}
          />
        }
      />

      <SettingRow
        label="Approve patches before they are applied"
        hint="Recommended. With this off, a proposed fix is written to your workspace without asking first."
        control={
          <Toggle
            label="Approve patches before they are applied"
            checked={preferences.require_patch_approval}
            disabled={saving === "require_patch_approval"}
            onChange={(value) => void save({ require_patch_approval: value })}
          />
        }
      />
    </Section>
  );
}

/* -------------------------------------------------------------- Instance -- */

/**
 * Read-only deployment facts, kept separate from the controls above so nothing
 * here can be mistaken for something the user can change. No credentials are
 * sent to this page — only whether one is configured.
 */
function InstanceSection() {
  const { data: system } = useAsync(getSystem, []);

  if (!system) return null;

  return (
    <Section
      title="This instance"
      description="Set by whoever deployed API Doctor. Shown so you know what your runs actually do."
      icon={<Cpu className="h-3.5 w-3.5" />}
    >
      <SettingRow
        label="AI model"
        hint="The model every analysis is sent to."
        control={
          <span className="mono text-xs font-medium text-ink">{system.openai_model}</span>
        }
      />
      <SettingRow
        label="Analysis engine"
        hint={
          system.openai_configured
            ? "AI analysis is available on this instance."
            : "No API key is configured, so analysis falls back to the deterministic rule engine and is labelled as such wherever it appears."
        }
        control={
          <Badge tone={system.openai_configured ? "brand" : "warn"}>
            {system.reasoning_engine}
          </Badge>
        }
      />
      <SettingRow
        label="Code execution"
        hint={
          system.execution_isolated
            ? "Your uploaded code runs inside an isolated container."
            : "Your uploaded code runs on the host without container isolation."
        }
        control={
          <Badge tone={system.execution_isolated ? "ok" : "warn"}>
            {system.execution_isolated ? "Container isolated" : "No isolation"}
          </Badge>
        }
      />
    </Section>
  );
}

/* ---------------------------------------------------------------- Danger -- */

function DangerSection({ onDeleted }: { onDeleted: () => Promise<void> }) {
  const [open, setOpen] = React.useState(false);
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteAccount(password);
      await onDeleted();
    } catch (exc) {
      setError(errorMessage(exc, "Could not delete your account."));
      setBusy(false);
    }
  };

  return (
    <Section
      title="Delete account"
      tone="danger"
      icon={<Trash2 className="h-3.5 w-3.5" />}
      description="Permanent. There is no undo and no recovery."
    >
      <SettingRow
        label="Delete this account"
        hint="Your account, every project you own, their workspaces and their entire test history are removed immediately."
        control={
          <Button
            variant="danger"
            className="w-full sm:w-auto"
            onClick={() => {
              setPassword("");
              setError(null);
              setOpen(true);
            }}
          >
            Delete account
          </Button>
        }
      />

      <ConfirmDialog
        open={open}
        title="Delete your account?"
        description="This removes your account and every project you own, including all workspaces and test history. It cannot be undone."
        confirmLabel="Delete my account"
        confirmText="DELETE"
        busy={busy}
        error={error}
        extra={
          <Field label="Confirm your password" htmlFor="delete-password">
            <Input
              id="delete-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
          </Field>
        }
        onConfirm={remove}
        onCancel={() => setOpen(false)}
      />
    </Section>
  );
}
