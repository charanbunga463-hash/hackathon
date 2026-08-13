"use client";

/**
 * The one way a list of projects is rendered.
 *
 * Both the Dashboard and the Projects page use it, so "my projects" looks and
 * behaves the same wherever the user meets it. On a phone the table collapses
 * into stacked cards rather than being allowed to overflow the viewport — a
 * project row has four facts, and four facts do not fit across 360 pixels.
 */

import { Download, FolderPlus, Route, Trash2 } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge, Button, ConfirmDialog, EmptyState, StatusDot } from "@/components/ui/primitives";
import { deleteProject, exportProjectUrl } from "@/lib/api";
import { errorMessage } from "@/lib/auth";
import { formatRelative, type Tone } from "@/lib/utils";
import type { ProjectStatus, ProjectSummary } from "@/types";

const STATUS_TONE: Record<ProjectStatus, Tone> = {
  created: "muted",
  analyzing: "info",
  ready: "info",
  healthy: "ok",
  failing: "danger",
  repairing: "warn",
  repaired: "ok",
  error: "danger",
};

const STATUS_LABEL: Record<ProjectStatus, string> = {
  created: "New",
  analyzing: "Analyzing",
  ready: "Ready",
  healthy: "Healthy",
  failing: "Failing",
  repairing: "Repairing",
  repaired: "Repaired",
  error: "Error",
};

/** Statuses that mean work is happening right now, so the pip should pulse. */
const BUSY: ProjectStatus[] = ["analyzing", "repairing"];

export function ProjectsEmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="card">
      <EmptyState
        icon={<FolderPlus className="h-5 w-5" />}
        title="No projects yet"
        description="Upload a .zip of your API project and API Doctor will analyse it, find what is broken, and propose a verified fix."
        action={
          <Button variant="primary" onClick={onCreate}>
            Create your first project
          </Button>
        }
      />
    </div>
  );
}

export function ProjectTable({
  projects,
  onChanged,
  showDelete = true,
}: {
  projects: ProjectSummary[];
  onChanged?: () => void;
  showDelete?: boolean;
}) {
  const [pending, setPending] = React.useState<ProjectSummary | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const remove = async () => {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      await deleteProject(pending.id);
      setPending(null);
      onChanged?.();
    } catch (exc) {
      setError(errorMessage(exc, "Could not delete that project."));
    } finally {
      setBusy(false);
    }
  };

  const askDelete = (project: ProjectSummary) => {
    setError(null);
    setPending(project);
  };

  return (
    <>
      {/* --------------------------------------------------- phones: cards */}
      <ul className="space-y-3 md:hidden">
        {projects.map((project) => (
          <li key={project.id} className="card card-interactive p-4">
            <div className="flex items-start justify-between gap-3">
              <Link
                href={`/projects/${project.id}`}
                className="min-w-0 truncate text-sm font-semibold text-ink hover:text-brand-ink"
                title={project.name}
              >
                {project.name}
              </Link>
              <Badge tone={STATUS_TONE[project.status]}>
                <StatusDot
                  tone={STATUS_TONE[project.status]}
                  pulse={BUSY.includes(project.status)}
                />
                {STATUS_LABEL[project.status]}
              </Badge>
            </div>
            <p className="mt-1.5 flex items-center gap-3 text-2xs text-muted">
              <span className="flex items-center gap-1">
                <Route className="h-3 w-3" aria-hidden />
                {project.route_count} routes
              </span>
              <span>{formatRelative(project.updated_at)}</span>
            </p>
            <div className="mt-3 flex items-center gap-2">
              <Link
                href={`/projects/${project.id}`}
                className="flex-1 rounded-lg border border-brand-line bg-brand-soft px-3 py-1.5 text-center text-xs font-semibold text-brand-ink"
              >
                Open
              </Link>
              <a
                href={exportProjectUrl(project.id)}
                download
                title="Export the project as a ZIP"
                className="rounded-lg border border-line bg-surface p-2 text-muted"
              >
                <Download className="h-3.5 w-3.5" />
              </a>
              {showDelete ? (
                <button
                  onClick={() => askDelete(project)}
                  aria-label={`Delete ${project.name}`}
                  className="rounded-lg border border-line bg-surface p-2 text-danger"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>

      {/* -------------------------------------------------- desktop: table */}
      <div className="card hidden overflow-hidden md:block">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-line bg-elevated/60 text-left">
              <Th>Project</Th>
              <Th>Routes</Th>
              <Th>Status</Th>
              <Th>Last updated</Th>
              <Th className="text-right">Actions</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {projects.map((project) => (
              <tr key={project.id} className="group transition-colors hover:bg-brand-soft/50">
                <td className="px-4 py-3">
                  <Link
                    href={`/projects/${project.id}`}
                    className="block truncate font-semibold text-ink transition-colors group-hover:text-brand-ink"
                    title={project.name}
                  >
                    {project.name}
                  </Link>
                  <p className="truncate text-2xs text-faint">{project.framework}</p>
                </td>
                <td className="px-4 py-3 tabular-nums text-muted">{project.route_count}</td>
                <td className="px-4 py-3">
                  <Badge tone={STATUS_TONE[project.status]}>
                    <StatusDot
                      tone={STATUS_TONE[project.status]}
                      pulse={BUSY.includes(project.status)}
                    />
                    {STATUS_LABEL[project.status]}
                  </Badge>
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-xs text-muted">
                  {formatRelative(project.updated_at)}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    <Link
                      href={`/projects/${project.id}`}
                      className="rounded-lg px-3 py-1.5 text-xs font-semibold text-brand-ink transition-colors hover:bg-brand-soft"
                    >
                      Open
                    </Link>
                    <a
                      href={exportProjectUrl(project.id)}
                      download
                      className="rounded-lg p-2 text-faint transition-colors hover:bg-elevated hover:text-brand-ink"
                      title="Export the project as a ZIP"
                    >
                      <Download className="h-3.5 w-3.5" />
                    </a>
                    {showDelete ? (
                      <button
                        onClick={() => askDelete(project)}
                        aria-label={`Delete ${project.name}`}
                        className="rounded-lg p-2 text-faint transition-colors hover:bg-danger-soft hover:text-danger-ink"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ConfirmDialog
        open={pending !== null}
        title="Delete this project?"
        description={
          <>
            <strong className="text-ink">{pending?.name}</strong>, its workspace, its snapshots
            and its entire test history will be removed. This cannot be undone.
          </>
        }
        confirmLabel="Delete project"
        confirmText={pending?.name}
        busy={busy}
        error={error}
        onConfirm={remove}
        onCancel={() => {
          setPending(null);
          setError(null);
        }}
      />
    </>
  );
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      className={`px-4 py-2.5 text-2xs font-bold uppercase tracking-wider text-muted ${className ?? ""}`}
    >
      {children}
    </th>
  );
}
