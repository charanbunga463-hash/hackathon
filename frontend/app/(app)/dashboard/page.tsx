"use client";

/**
 * Dashboard — Executive AI Doctor Command Center.
 *
 * Provides real-time visibility into monitored projects, API route surfaces,
 * system health metrics, active sandbox engine, quick workflow triggers, and
 * live streaming agent activities.
 */

import {
  Activity,
  AlertCircle,
  ArrowUpRight,
  CheckCircle2,
  Cpu,
  FileCode2,
  FlaskConical,
  FolderKanban,
  Globe,
  Plus,
  RefreshCw,
  Route,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { ActivityStream } from "@/components/agent-activity/activity-stream";
import { useAuth } from "@/components/auth/auth-context";
import {
  NewProjectButton,
  NewProjectDialog,
} from "@/components/projects/new-project-dialog";
import {
  ProjectsEmptyState,
  ProjectTable,
} from "@/components/projects/project-table";
import {
  Badge,
  Button,
  ErrorNote,
  Panel,
  PanelHeader,
  Spinner,
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

  // Calculate metrics
  const totalProjects = projects.length;
  const healthyProjects = projects.filter((p) => p.status === "healthy" || p.status === "repaired").length;
  const failingProjects = projects.filter((p) => p.status === "failing" || p.status === "error").length;
  const inProgressProjects = projects.filter((p) => p.status === "repairing" || p.status === "analyzing").length;
  const totalRoutes = projects.reduce((acc, p) => acc + (p.route_count || 0), 0);

  const healthRate = totalProjects > 0 ? Math.round((healthyProjects / totalProjects) * 100) : 100;
  const healthTone = healthRate >= 80 ? "ok" : healthRate >= 50 ? "warn" : "danger";

  return (
    <div className="space-y-6 animate-fade-up">
      {/* Hero Header */}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-line pb-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-ink">
              Welcome back, {firstName}
            </h1>
            <span className="text-xl">👋</span>
          </div>
          <p className="max-w-2xl text-xs sm:text-sm text-muted leading-relaxed">
            API Doctor autonomous agent is monitoring system endpoints, detecting failure root causes, and proposing verified code fixes.
          </p>
        </div>

        <div className="flex items-center gap-2.5 shrink-0">
          <Button variant="secondary" size="sm" onClick={refresh} title="Refresh dashboard data">
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <NewProjectButton
            onCreated={(project) => router.push(`/projects/${project.id}`)}
          />
        </div>
      </header>

      {/* Metrics Grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Total Projects"
          value={
            <div className="flex items-baseline justify-between">
              <span>{totalProjects}</span>
              <span className="text-xs font-normal text-muted">
                {healthyProjects} healthy
              </span>
            </div>
          }
          hint={
            failingProjects > 0 ? (
              <span className="text-danger font-medium">{failingProjects} project(s) failing</span>
            ) : (
              "All projects operational"
            )
          }
          icon={<FolderKanban className="h-4 w-4" />}
          tone={failingProjects > 0 ? "danger" : "ok"}
        />

        <StatTile
          label="API Surface Routes"
          value={totalRoutes}
          hint="Discovered static endpoints"
          icon={<Route className="h-4 w-4" />}
          tone="accent"
        />

        <StatTile
          label="System Health Index"
          value={`${healthRate}%`}
          hint={
            <div className="flex items-center gap-1.5 mt-0.5">
              <div className="h-1.5 flex-1 rounded-full bg-elevated overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    healthRate >= 80 ? "bg-ok" : healthRate >= 50 ? "bg-warn" : "bg-danger"
                  }`}
                  style={{ width: `${healthRate}%` }}
                />
              </div>
              <span className="text-2xs text-muted tabular-nums">{healthyProjects}/{totalProjects}</span>
            </div>
          }
          icon={<ShieldCheck className="h-4 w-4" />}
          tone={healthTone}
        />

        <StatTile
          label="Sandbox Execution"
          value={
            <span className="text-sm font-semibold truncate block">
              {sandbox?.isolated ? "Container Sandbox" : "Local Host Runner"}
            </span>
          }
          hint={
            sandbox?.isolated ? (
              <span className="text-ok font-medium">Docker isolated mode</span>
            ) : (
              <span className="text-warn font-medium">Local trusted mode</span>
            )
          }
          icon={<Cpu className="h-4 w-4" />}
          tone={sandbox?.isolated ? "ok" : "warn"}
        />
      </div>

      {/* Main Content Layout */}
      <div className="grid gap-6 xl:grid-cols-12">
        {/* Left Column - Projects & Quick Workflows (8 cols) */}
        <div className="xl:col-span-8 space-y-6 min-w-0">
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-ink">Projects Directory</h2>
                <Badge tone="muted">{projects.length}</Badge>
              </div>

              {projects.length > 0 ? (
                <Link
                  href="/projects"
                  className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
                >
                  View all projects <ArrowUpRight className="h-3 w-3" />
                </Link>
              ) : null}
            </div>

            {error && !projectsData ? (
              <ErrorNote message={error} />
            ) : loading && !projectsData ? (
              <div className="flex items-center justify-center gap-2.5 rounded-lg border border-line bg-surface py-16">
                <Spinner className="h-5 w-5" />
                <span className="text-sm text-muted">Loading monitored projects…</span>
              </div>
            ) : projects.length === 0 ? (
              <NoProjects onCreated={(id) => router.push(`/projects/${id}`)} />
            ) : (
              <ProjectTable projects={projects} onChanged={refresh} />
            )}
          </section>

          {/* Quick Workflows Panel */}
          <section className="space-y-3">
            <h2 className="text-base font-semibold text-ink">AI Doctor Workflows</h2>
            <div className="grid gap-3 sm:grid-cols-3">
              <div
                onClick={() => setDialogOpen(true)}
                className="panel lift group cursor-pointer p-4 hover:border-accent/50"
              >
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent/10 text-accent group-hover:bg-accent group-hover:text-white transition-colors">
                  <Plus className="h-4 w-4" />
                </div>
                <h3 className="mt-3 text-xs font-semibold text-ink">Add New API Project</h3>
                <p className="mt-1 text-2xs text-muted leading-relaxed">
                  Upload FastAPI, Flask, Express or Python backend project files for diagnostic scanning.
                </p>
              </div>

              <div className="panel lift p-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-info/10 text-info">
                  <FlaskConical className="h-4 w-4" />
                </div>
                <h3 className="mt-3 text-xs font-semibold text-ink">Automated Probe & Test</h3>
                <p className="mt-1 text-2xs text-muted leading-relaxed">
                  Run test suites or HTTP probes to catch broken endpoints before production.
                </p>
              </div>

              <div className="panel lift p-4">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-ok/10 text-ok">
                  <Wrench className="h-4 w-4" />
                </div>
                <h3 className="mt-3 text-xs font-semibold text-ink">Self-Healing Patch Agent</h3>
                <p className="mt-1 text-2xs text-muted leading-relaxed">
                  Generates minimal diff patches, applies code fixes, and verifies tests pass cleanly.
                </p>
              </div>
            </div>
          </section>
        </div>

        {/* Right Column - Sandbox Info & Live Activity Feed (4 cols) */}
        <div className="xl:col-span-4 space-y-6 min-w-0">
          {/* Sandbox Info Widget */}
          <Panel className="p-4 space-y-3 border-line bg-surface">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Cpu className="h-4 w-4 text-accent" />
                <span className="text-xs font-semibold text-ink">Execution Environment</span>
              </div>
              <Badge tone={sandbox?.isolated ? "ok" : "warn"}>
                {sandbox?.isolated ? "Isolated" : "Local Mode"}
              </Badge>
            </div>
            <p className="text-2xs text-muted leading-relaxed">
              {sandbox?.isolated
                ? "Code runs inside isolated Docker containers with full resource boundaries."
                : "Project code runs directly on host runner. CPU, memory, and filesystem are non-restricted."}
            </p>
            <div className="pt-1 border-t border-line/60 flex items-center justify-between text-2xs text-faint">
              <span>Engine: {sandbox?.kind ?? "local_process"}</span>
              <Link href="/settings" className="text-accent hover:underline">
                Environment settings
              </Link>
            </div>
          </Panel>

          {/* Real-time Agent Activity Stream */}
          <Panel className="flex h-[460px] flex-col overflow-hidden">
            <ActivityStream
              events={events}
              connected={connected}
              className="flex-1 min-h-0 h-full overflow-hidden"
              emptyHint="Agent streaming engine connected. Run tests or start repairs to watch agent events."
            />
          </Panel>
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

/**
 * The empty state carries its own create button.
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

