"use client";

/**
 * Dashboard — the state of every project you own, in one screen.
 *
 * The order is deliberate: how healthy things are, then what needs attention,
 * then what the agent is doing right now. Nothing here is decorative — each
 * number is derived from the project list the backend actually returned, and
 * "healthy" only counts projects the backend called healthy or repaired.
 */

import {
  ArrowUpRight,
  Cpu,
  FlaskConical,
  FolderKanban,
  Plus,
  RefreshCw,
  Route,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { ActivityStream } from "@/components/agent-activity/activity-stream";
import { useAuth } from "@/components/auth/auth-context";
import { NewProjectButton, NewProjectDialog } from "@/components/projects/new-project-dialog";
import { ProjectsEmptyState, ProjectTable } from "@/components/projects/project-table";
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  IconTile,
  LoadingBlock,
  Progress,
  StatTile,
} from "@/components/ui/primitives";
import { useEvents, usePolling } from "@/hooks/useEvents";
import { getSandbox, listProjects } from "@/lib/api";

export default function DashboardPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [dialogOpen, setDialogOpen] = React.useState(false);

  const { data: projectsData, error, loading, refresh } = usePolling(listProjects, 15_000);
  const { data: sandbox } = usePolling(getSandbox, 60_000);
  const { events, connected } = useEvents();

  const projects = projectsData ?? [];
  const firstName = user?.name?.trim().split(/\s+/)[0] || "there";

  const total = projects.length;
  const healthy = projects.filter((p) => p.status === "healthy" || p.status === "repaired").length;
  const failing = projects.filter((p) => p.status === "failing" || p.status === "error").length;
  const routes = projects.reduce((sum, p) => sum + (p.route_count || 0), 0);

  const healthRate = total > 0 ? Math.round((healthy / total) * 100) : 100;
  const healthTone = healthRate >= 80 ? "ok" : healthRate >= 50 ? "warn" : "danger";

  return (
    <div className="space-y-6 animate-fade-up">
      {/* ------------------------------------------------------------ hero */}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="eyebrow">Workspace</p>
          <h1 className="mt-1.5 text-2xl font-bold tracking-tight text-ink sm:text-3xl">
            Welcome back, {firstName}
          </h1>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">
            API Doctor watches your endpoints, finds the root cause of each failure against real
            source and test output, and only calls a repair fixed once your own tests prove it.
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Button variant="secondary" onClick={refresh} title="Refresh dashboard data">
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
          <NewProjectButton onCreated={(project) => router.push(`/projects/${project.id}`)} />
        </div>
      </header>

      {/* --------------------------------------------------------- metrics */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Projects"
          value={total}
          tone={failing > 0 ? "danger" : "brand"}
          icon={<FolderKanban className="h-3.5 w-3.5" />}
          hint={
            failing > 0 ? (
              <span className="font-semibold text-danger-ink">
                {failing} project{failing === 1 ? "" : "s"} failing
              </span>
            ) : (
              `${healthy} healthy · all operational`
            )
          }
        />

        <StatTile
          label="API routes"
          value={routes}
          tone="info"
          icon={<Route className="h-3.5 w-3.5" />}
          hint="Discovered by static analysis"
        />

        <StatTile
          label="Health index"
          value={`${healthRate}%`}
          tone={healthTone}
          icon={<ShieldCheck className="h-3.5 w-3.5" />}
          hint={
            <span className="flex items-center gap-2">
              <Progress value={healthRate / 100} tone={healthTone} className="h-1.5 flex-1" />
              <span className="shrink-0 tabular-nums">
                {healthy}/{total}
              </span>
            </span>
          }
        />

        <StatTile
          label="Execution"
          value={
            <span className="block truncate text-base">
              {sandbox?.isolated ? "Container sandbox" : "Local host runner"}
            </span>
          }
          tone={sandbox?.isolated ? "ok" : "warn"}
          icon={<Cpu className="h-3.5 w-3.5" />}
          hint={sandbox?.isolated ? "Docker isolated mode" : "No container isolation"}
        />
      </div>

      {/* ----------------------------------------------------------- body */}
      <div className="grid gap-6 xl:grid-cols-12">
        <div className="min-w-0 space-y-6 xl:col-span-8">
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 text-base font-bold text-ink">
                Your projects
                <Badge tone="muted">{projects.length}</Badge>
              </h2>
              {projects.length > 0 ? (
                <Link
                  href="/projects"
                  className="inline-flex items-center gap-1 text-xs font-semibold text-brand-ink hover:underline"
                >
                  View all
                  <ArrowUpRight className="h-3 w-3" aria-hidden />
                </Link>
              ) : null}
            </div>

            {error && !projectsData ? (
              <ErrorNote message={error} />
            ) : loading && !projectsData ? (
              <LoadingBlock label="Loading monitored projects…" />
            ) : projects.length === 0 ? (
              <NoProjects onCreated={(id) => router.push(`/projects/${id}`)} />
            ) : (
              <ProjectTable projects={projects} onChanged={refresh} />
            )}
          </section>

          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">What the agent does</h2>
            <div className="grid gap-4 sm:grid-cols-3">
              <WorkflowCard
                tone="brand"
                icon={<Plus className="h-4 w-4" />}
                title="Add a project"
                body="Upload a FastAPI, Flask, Django or other Python API as a .zip and it is analysed on arrival."
                onClick={() => setDialogOpen(true)}
              />
              <WorkflowCard
                tone="info"
                icon={<FlaskConical className="h-4 w-4" />}
                title="Probe and test"
                body="Run the project's own suite, or call every discovered endpoint and record what really came back."
              />
              <WorkflowCard
                tone="ok"
                icon={<Wrench className="h-4 w-4" />}
                title="Repair and verify"
                body="A minimal diff, your approval, then the suite runs again to prove the failure is gone."
              />
            </div>
          </section>
        </div>

        {/* ---------------------------------------------------- live feed */}
        <div className="min-w-0 xl:col-span-4">
          <Card className="flex h-[32rem] flex-col overflow-hidden xl:sticky xl:top-20">
            <ActivityStream
              events={events}
              connected={connected}
              emptyHint="The stream is connected. Run tests or start a repair to watch each agent step arrive."
            />
          </Card>
        </div>
      </div>

      <NewProjectDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onCreated={(project) => {
          setDialogOpen(false);
          router.push(`/projects/${project.id}`);
        }}
      />
    </div>
  );
}

function WorkflowCard({
  tone,
  icon,
  title,
  body,
  onClick,
}: {
  tone: "brand" | "info" | "ok";
  icon: React.ReactNode;
  title: string;
  body: string;
  onClick?: () => void;
}) {
  const content = (
    <>
      <IconTile tone={tone}>{icon}</IconTile>
      <h3 className="mt-3.5 text-sm font-bold text-ink">{title}</h3>
      <p className="mt-1.5 text-xs leading-relaxed text-muted">{body}</p>
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className="card card-interactive p-4 text-left"
      >
        {content}
      </button>
    );
  }
  return <div className="card p-4">{content}</div>;
}

/** The empty state carries its own create dialog. */
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
