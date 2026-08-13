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

import { FileArchive, Plus, ShieldCheck, Upload, X } from "lucide-react";
import * as React from "react";

import { Button, ErrorNote, Field, Input, Modal } from "@/components/ui/primitives";
import { uploadProject } from "@/lib/api";
import { errorMessage } from "@/lib/auth";
import { cn, formatBytes } from "@/lib/utils";
import type { Project } from "@/types";

export function NewProjectButton({
  onCreated,
  variant = "primary",
  children = "New project",
}: {
  onCreated: (project: Project) => void;
  variant?: "primary" | "secondary";
  children?: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant={variant} onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4" aria-hidden />
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
  const [dragging, setDragging] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (open) {
      setFile(null);
      setName("");
      setError(null);
      setDragging(false);
    }
  }, [open]);

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

  const accept = (dropped?: File | null) => {
    if (!dropped) return;
    setFile(dropped);
    setError(null);
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      busy={busy}
      title="New project"
      description="Upload a .zip of your API project. It gets its own isolated workspace and is private to your account."
      icon={
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-gradient text-white shadow-glow">
          <Upload className="h-4 w-4" aria-hidden />
        </span>
      }
    >
      <form onSubmit={submit} className="space-y-4">
        {/* ------------------------------------------------------ dropzone */}
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            accept(event.dataTransfer.files?.[0]);
          }}
          className={cn(
            "relative rounded-2xl border-2 border-dashed p-6 text-center transition-colors",
            dragging
              ? "border-brand bg-brand-soft"
              : file
                ? "border-ok-line bg-ok-soft"
                : "border-line-strong bg-sunken hover:border-brand-line hover:bg-brand-soft/50",
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".zip,application/zip"
            required
            disabled={busy}
            onChange={(event) => accept(event.target.files?.[0] ?? null)}
            className="absolute inset-0 cursor-pointer opacity-0"
            aria-label="Project archive"
          />

          {file ? (
            <div className="relative flex items-center justify-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-ok-line bg-white text-ok-ink">
                <FileArchive className="h-4.5 w-4.5" aria-hidden />
              </span>
              <span className="min-w-0 text-left">
                <span className="block truncate text-sm font-semibold text-ink">{file.name}</span>
                <span className="block text-2xs text-muted">{formatBytes(file.size)}</span>
              </span>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setFile(null);
                  if (inputRef.current) inputRef.current.value = "";
                }}
                aria-label="Choose a different archive"
                className="relative z-10 rounded-lg p-1.5 text-muted transition-colors hover:bg-white hover:text-ink"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <div className="pointer-events-none">
              <span className="mx-auto flex h-11 w-11 items-center justify-center rounded-2xl border border-brand-line bg-brand-soft text-brand">
                <Upload className="h-5 w-5" aria-hidden />
              </span>
              <p className="mt-3 text-sm font-semibold text-ink">
                Drop your <span className="mono">.zip</span> here
              </p>
              <p className="mt-0.5 text-2xs text-muted">or click to browse your files</p>
            </div>
          )}
        </div>

        <p className="flex items-start gap-2 rounded-xl border border-info-line bg-info-soft px-3 py-2 text-2xs leading-relaxed text-info-ink">
          <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
          Archives are inspected before extraction: path traversal, absolute paths, symlinks,
          oversized members and zip bombs are all rejected.
        </p>

        <Field
          label="Project name"
          htmlFor="project-name"
          hint="Optional — defaults to the archive name."
        >
          <Input
            id="project-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="My API"
            maxLength={80}
            disabled={busy}
          />
        </Field>

        {error ? <ErrorNote message={error} /> : null}

        <div className="flex flex-col-reverse gap-2 border-t border-line pt-4 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={!file} loading={busy}>
            {busy ? "Uploading and analysing…" : "Create project"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
