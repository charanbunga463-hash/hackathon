"use client";

/**
 * The one way a list of projects is rendered.
 *
 * Both the Dashboard and the Projects page use it, so "my projects" looks and
 * behaves the same wherever the user meets it. Columns beyond name and action
 * are progressively dropped on narrow screens rather than being allowed to
 * overflow the viewport.
 */

import { FolderPlus, Trash2 } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
} from "@/components/ui/primitives";
import { deleteProject } from "@/lib/api";
import { errorMessage } from "@/lib/auth";
import { formatRelative } from "@/lib/utils";
import type { ProjectStatus, ProjectSummary } from "@/types";

const STATUS_TONE: Record<ProjectStatus, "ok" | "warn" | "danger" | "info" | "muted"> = {
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

export function ProjectsEmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="rounded-lg border border-line bg-surface">
      <EmptyState
        icon={<FolderPlus className="h-8 w-8" />}
        title="No projects yet"
        description="Create your first project to begin testing and debugging APIs."
        action={
          <Button variant="primary" onClick={onCreate}>
            Create Project
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

  return (
    <>
      {/* The table scrolls inside this box; the page itself never scrolls
          sideways, which is the thing that makes a layout feel broken. */}
      <div className="overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full min-w-[34rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-left">
              <Th>Project Name</Th>
              <Th className="hidden sm:table-cell">APIs</Th>
              <Th className="hidden md:table-cell">Status</Th>
              <Th className="hidden sm:table-cell">Last Updated</Th>
              <Th className="text-right">Actions</Th>
            </tr>
          </thead>
          <tbody>
            {projects.map((project) => (
              <tr
                key={project.id}
                className="border-b border-line last:border-0 hover:bg-elevated/40"
              >
                <td className="px-4 py-3">
                  <Link
                    href={`/projects/${project.id}`}
                    className="block truncate font-medium text-ink hover:text-accent"
                    title={project.name}
                  >
                    {project.name}
                  </Link>
                  <p className="truncate text-xs text-faint sm:hidden">
                    {project.route_count} APIs · {formatRelative(project.updated_at)}
                  </p>
                </td>
                <td className="hidden px-4 py-3 tabular-nums text-muted sm:table-cell">
                  {project.route_count}
                </td>
                <td className="hidden px-4 py-3 md:table-cell">
                  <Badge tone={STATUS_TONE[project.status]}>
                    {STATUS_LABEL[project.status]}
                  </Badge>
                </td>
                <td className="hidden whitespace-nowrap px-4 py-3 text-muted sm:table-cell">
                  {formatRelative(project.updated_at)}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    <Link
                      href={`/projects/${project.id}`}
                      className="rounded-md px-2.5 py-1 text-xs font-medium text-accent hover:bg-accent/10"
                    >
                      Open
                    </Link>
                    {showDelete ? (
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete ${project.name}`}
                        onClick={() => {
                          setError(null);
                          setPending(project);
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5 text-danger" />
                      </Button>
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
            <strong className="text-ink">{pending?.name}</strong>, its workspace,
            its snapshots and its entire test history will be removed. This cannot
            be undone.
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
      className={`px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-faint ${className ?? ""}`}
    >
      {children}
    </th>
  );
}
