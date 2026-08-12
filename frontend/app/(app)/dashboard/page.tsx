"use client";

/**
 * Dashboard — the answer to "what do I have, and what do I do next".
 *
 * It shows the user's projects and nothing else. There is no activity feed, no
 * chart and no system panel here: a dashboard whose widgets are empty until you
 * have done something is a worse first impression than one clear next step, and
 * the details it used to duplicate live on the pages that own them.
 */

import { useRouter } from "next/navigation";
import Link from "next/link";
import * as React from "react";

import { useAuth } from "@/components/auth/auth-context";
import {
  NewProjectButton,
  NewProjectDialog,
} from "@/components/projects/new-project-dialog";
import {
  ProjectsEmptyState,
  ProjectTable,
} from "@/components/projects/project-table";
import { ErrorNote, Spinner } from "@/components/ui/primitives";
import { usePolling } from "@/hooks/useEvents";
import { listProjects } from "@/lib/api";

/** How many rows the dashboard shows before deferring to the Projects page. */
const PREVIEW_LIMIT = 5;

export default function DashboardPage() {
  const { user } = useAuth();
  const router = useRouter();
  // Projects change when the user acts, not on their own, so this refreshes
  // slowly and mostly relies on explicit refetches after a create or delete.
  const { data, error, loading, refresh } = usePolling(listProjects, 30_000);

  const projects = data ?? [];
  const firstName = user?.name?.trim().split(/\s+/)[0] || "there";

  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight text-ink">
          Welcome back, {firstName}
        </h1>
        <p className="max-w-2xl text-sm text-muted">
          API Doctor finds what is broken in your API, explains why, proposes a
          fix, and proves it by running your project&apos;s own tests.
        </p>
      </header>

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-ink">Projects</h2>
          {projects.length > 0 ? (
            <NewProjectButton
              onCreated={(project) => router.push(`/projects/${project.id}`)}
            />
          ) : null}
        </div>

        {error && !data ? (
          <ErrorNote message={error} />
        ) : loading && !data ? (
          <div className="flex items-center justify-center gap-2.5 rounded-lg border border-line bg-surface py-16">
            <Spinner className="h-5 w-5" />
            <span className="text-sm text-muted">Loading projects…</span>
          </div>
        ) : projects.length === 0 ? (
          <NoProjects onCreated={(id) => router.push(`/projects/${id}`)} />
        ) : (
          <>
            <ProjectTable
              projects={projects.slice(0, PREVIEW_LIMIT)}
              onChanged={refresh}
            />
            {projects.length > PREVIEW_LIMIT ? (
              <p className="text-xs text-muted">
                Showing {PREVIEW_LIMIT} of {projects.length}.{" "}
                <Link href="/projects" className="font-medium text-accent hover:underline">
                  View all projects
                </Link>
              </p>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}

/**
 * The empty state carries its own create button rather than pointing at one
 * elsewhere: the only thing a new account can usefully do is start a project.
 */
function NoProjects({ onCreated }: { onCreated: (projectId: string) => void }) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <ProjectsEmptyState onCreate={() => setOpen(true)} />
      <NewProjectDialog
        open={open}
        onClose={() => setOpen(false)}
        onCreated={(project) => {
          setOpen(false);
          onCreated(project.id);
        }}
      />
    </>
  );
}
