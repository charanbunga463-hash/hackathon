"use client";

/**
 * The single "create a project" flow.
 *
 * One dialog, reached from one button, from both the Dashboard and the Projects
 * page — rather than an inline panel on one page and a different control on
 * another. The upload is genuinely slow (the archive is scanned, extracted and
 * statically analysed before the response), so the button reports its own
 * progress and refuses a second submission while one is in flight.
 */

import { Upload, X } from "lucide-react";
import * as React from "react";

import { Button, ErrorNote, Field, Input } from "@/components/ui/primitives";
import { uploadProject } from "@/lib/api";
import { errorMessage } from "@/lib/auth";
import type { Project } from "@/types";

export function NewProjectButton({
  onCreated,
  variant = "primary",
  children = "+ New Project",
}: {
  onCreated: (project: Project) => void;
  variant?: "primary" | "secondary";
  children?: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant={variant} onClick={() => setOpen(true)}>
        {children}
      </Button>
      <NewProjectDialog
        open={open}
        onClose={() => setOpen(false)}
        onCreated={(project) => {
          setOpen(false);
          onCreated(project);
        }}
      />
    </>
  );
}

export function NewProjectDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (project: Project) => void;
}) {
  const [file, setFile] = React.useState<File | null>(null);
  const [name, setName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setFile(null);
      setName("");
      setError(null);
    }
  }, [open]);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    // Guarding on `busy` as well as disabling the button: a form can also be
    // submitted with Enter, and a double upload would create two projects.
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    try {
      onCreated(await uploadProject(file, name.trim() || undefined));
    } catch (exc) {
      setError(errorMessage(exc, "Could not create that project."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-4 sm:items-center"
      onClick={() => !busy && onClose()}
      role="presentation"
    >
      <form
        onSubmit={submit}
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-lg rounded-lg border border-line bg-surface shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-label="Create a project"
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-ink">New project</h2>
            <p className="mt-0.5 text-xs text-muted">
              Upload a .zip of your API project. It gets its own isolated
              workspace and is private to your account.
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <Field
            label="Project archive"
            hint="Archives are inspected before extraction: path traversal, absolute paths, symlinks, oversized members and zip bombs are all rejected."
          >
            <input
              type="file"
              accept=".zip,application/zip"
              required
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              className="block w-full text-xs text-muted file:mr-3 file:rounded-md file:border-0 file:bg-elevated file:px-3 file:py-2 file:text-xs file:text-ink hover:file:bg-line/40"
            />
          </Field>

          <Field label="Project name" hint="Optional — defaults to the archive name.">
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="My API"
              maxLength={80}
            />
          </Field>

          {error ? <ErrorNote message={error} /> : null}
        </div>

        <div className="flex flex-col-reverse gap-2 border-t border-line px-5 py-3 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={!file} loading={busy}>
            <Upload className="h-3.5 w-3.5" aria-hidden />
            {busy ? "Uploading and analyzing…" : "Create Project"}
          </Button>
        </div>
      </form>
    </div>
  );
}
