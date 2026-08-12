"use client";

/**
 * Projects — every project this account owns.
 *
 * The list comes from `GET /api/projects`, which returns summaries scoped to
 * the authenticated user by the database. No filtering happens here, because
 * filtering in the browser would mean another user's projects had already been
 * sent to it.
 */

import { useRouter } from "next/navigation";
import * as React from "react";

import {
  NewProjectButton,
  NewProjectDialog,
} from "@/components/projects/new-project-dialog";
import {
  ProjectsEmptyState,
  ProjectTable,
} from "@/components/projects/project-table";
import { ErrorNote, PageHeader, Spinner } from "@/components/ui/primitives";
import { usePolling } from "@/hooks/useEvents";
import { listProjects } from "@/lib/api";

export default function ProjectsPage() {
  const router = useRouter();
  const { data, error, loading, refresh } = usePolling(listProjects, 30_000);
  const [dialogOpen, setDialogOpen] = React.useState(false);

  const projects = data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Projects"
        description="Each project gets its own isolated workspace and is private to your account."
        action={
          projects.length > 0 ? (
            <NewProjectButton
              onCreated={(project) => router.push(`/projects/${project.id}`)}
            />
          ) : null
        }
      />

      {error && !data ? <ErrorNote message={error} /> : null}

      {loading && !data ? (
        <div className="flex items-center justify-center gap-2.5 rounded-lg border border-line bg-surface py-16">
          <Spinner className="h-5 w-5" />
          <span className="text-sm text-muted">Loading projects…</span>
        </div>
      ) : projects.length === 0 && !error ? (
        <>
          <ProjectsEmptyState onCreate={() => setDialogOpen(true)} />
          <NewProjectDialog
            open={dialogOpen}
            onClose={() => setDialogOpen(false)}
            onCreated={(project) => {
              setDialogOpen(false);
              router.push(`/projects/${project.id}`);
            }}
          />
        </>
      ) : projects.length > 0 ? (
        <ProjectTable projects={projects} onChanged={refresh} />
      ) : null}
    </div>
  );
}
