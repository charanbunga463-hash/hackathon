"use client";

import {
  ArrowLeft,
  Bug,
  FileCode2,
  FlaskConical,
  Globe,
  PlayCircle,
  RefreshCw,
  Route as RouteIcon,
  Stethoscope,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { ActivityStream } from "@/components/agent-activity/activity-stream";
import { CodeView, FileTree } from "@/components/code-viewer/code-view";
import { DiagnosisPanel, FailureHeader } from "@/components/diagnosis/diagnosis-panel";
import { RepairSessionView } from "@/components/repair/repair-console";
import { TestHistory } from "@/components/test-results/test-history";
import {
  FailingTestList,
  TestOutput,
  TestRunSummary,
} from "@/components/test-results/test-results";
import {
  Badge,
  Button,
  EmptyState,
  ErrorNote,
  Panel,
  PanelHeader,
  Spinner,
  Tabs,
} from "@/components/ui/primitives";
import { useAsync, useEvents, usePolling } from "@/hooks/useEvents";
import {
  analyzeProject,
  diagnose,
  getActiveRepair,
  getProject,
  getProjectFile,
  getProjectFiles,
  latestExecution,
  probeApi,
  runTests,
  startRepair,
} from "@/lib/api";
import { SEVERITY_TONE, formatRelative, statusCodeTone } from "@/lib/utils";
import type {
  DiagnosisResult,
  ExecutionRecord,
  FileContent,
  NormalizedFailure,
} from "@/types";

type TabId = "overview" | "failures" | "repair" | "history" | "code";

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;

  const [tab, setTab] = React.useState<TabId>("overview");
  const [busy, setBusy] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [execution, setExecution] = React.useState<ExecutionRecord | null>(null);
  const [diagnosis, setDiagnosis] = React.useState<
    { failure: NormalizedFailure; diagnosis: DiagnosisResult; facts: string[]; note: string } | null
  >(null);

  // Poll fast only while a repair is actually in flight.
  //
  // These endpoints are not free: `/repair/{id}/active` costs two database
  // queries, and against a managed database in another region that is most of a
  // second each. Polling every 2.5s on an idle page kept the backend permanently
  // busy answering "no, still nothing". The live SSE stream below already pushes
  // the moment anything happens, so idle polling only needs to be a safety net
  // for a dropped stream.
  const [repairInFlight, setRepairInFlight] = React.useState(false);

  const { data: project, refresh: refreshProject } = usePolling(
    () => getProject(projectId),
    repairInFlight ? 10_000 : 60_000,
    [projectId, repairInFlight],
  );
  const { data: latest, refresh: refreshExecution } = usePolling(
    () => latestExecution(projectId),
    0,
    [projectId],
  );
  const { data: active, refresh: refreshActive } = usePolling(
    () => getActiveRepair(projectId),
    repairInFlight ? 2500 : 30_000,
    [projectId, repairInFlight],
  );
  const { events, connected } = useEvents(projectId);

  React.useEffect(() => {
    setRepairInFlight(active?.running ?? false);
  }, [active?.running]);

  // The stream is the real signal. Anything other than a heartbeat means state
  // changed, so refresh immediately rather than waiting for the next tick.
  const lastEvent = events.length ? events[events.length - 1] : null;
  React.useEffect(() => {
    if (!lastEvent || lastEvent.type === "heartbeat") return;
    void refreshActive();
    void refreshExecution();
  }, [lastEvent, refreshActive, refreshExecution]);

  React.useEffect(() => {
    if (latest?.record) setExecution(latest.record);
  }, [latest]);

  const record = execution ?? latest?.record ?? null;
  const failures = record ? (record.test_result?.failures ?? record.api_result?.failures ?? []) : [];
  const running = active?.running ?? false;
  const session = active?.session ?? null;

  const act = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  const onRunTests = () =>
    act("tests", async () => {
      const result = await runTests(projectId);
      setExecution(result);
      setDiagnosis(null);
      await refreshProject();
      if (result.failure_count) setTab("failures");
    });

  const onProbe = () =>
    act("probe", async () => {
      const result = await probeApi(projectId);
      setExecution(result);
      setDiagnosis(null);
      await refreshProject();
      if (result.failure_count) setTab("failures");
    });

  const onAnalyze = () =>
    act("analyze", async () => {
      await analyzeProject(projectId);
      await refreshProject();
    });

  const onDiagnose = (failureId?: string) =>
    act("diagnose", async () => {
      const result = await diagnose(projectId, failureId);
      setDiagnosis({
        failure: result.failure,
        diagnosis: result.diagnosis,
        facts: result.observed_facts,
        note: result.note,
      });
      setTab("failures");
    });

  const onRepair = (failureId?: string) =>
    act("repair", async () => {
      await startRepair(projectId, { mode: "test", failure_id: failureId ?? null });
      await refreshActive();
      setTab("repair");
    });

  if (!project) {
    return (
      <div className="flex items-center justify-center gap-2.5 py-24">
        <Spinner className="h-5 w-5" />
        <span className="text-sm text-muted">Loading project…</span>
      </div>
    );
  }

  const metadata = project.metadata;

  return (
    <div className="space-y-5">
      <header className="space-y-2">
        <Link
          href="/projects"
          className="inline-flex items-center gap-1 text-xs text-muted hover:text-ink"
        >
          <ArrowLeft className="h-3 w-3" /> All projects
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold tracking-tight text-ink">
              {project.name}
            </h1>
            <p className="truncate text-xs text-muted">
              {project.description ?? project.origin ?? project.source}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" loading={busy === "analyze"} disabled={busy !== null} onClick={onAnalyze}>
              <RefreshCw className="h-3.5 w-3.5" />
              {busy === "analyze" ? "Analyzing…" : "Analyze"}
            </Button>
            <Button size="sm" loading={busy === "tests"} disabled={busy !== null} onClick={onRunTests}>
              <FlaskConical className="h-3.5 w-3.5" />
              {busy === "tests" ? "Running tests…" : "Run tests"}
            </Button>
            <Button size="sm" loading={busy === "probe"} disabled={busy !== null} onClick={onProbe}>
              <Globe className="h-3.5 w-3.5" />
              {busy === "probe" ? "Testing API…" : "Test API"}
            </Button>
            <Button
              size="sm"
              variant="primary"
              loading={busy === "repair"}
              disabled={running || !failures.length || busy !== null}
              onClick={() => onRepair(failures[0]?.id)}
              title={
                !failures.length
                  ? "Run tests or probe the API first so there is a real failure to repair"
                  : undefined
              }
            >
              <Wrench className="h-3.5 w-3.5" />
              {running ? "Repair running…" : "Repair"}
            </Button>
          </div>
        </div>
      </header>

      {error ? <ErrorNote message={error} /> : null}

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "failures", label: "Failures", count: failures.length },
          { id: "repair", label: "Repair", count: session ? session.attempts.length : undefined },
          { id: "history", label: "History" },
          { id: "code", label: "Code" },
        ]}
      />

      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <div className="min-w-0 space-y-4">
          {tab === "overview" ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <Panel>
                  <PanelHeader title="Project" icon={<Stethoscope className="h-4 w-4" />} />
                  <div className="space-y-2 p-4 text-xs">
                    <Row label="Language" value={metadata?.language ?? "—"} />
                    <Row label="Framework" value={metadata?.framework ?? "—"} />
                    <Row label="Entry point" value={metadata?.entry_point ?? "—"} mono />
                    <Row label="Test framework" value={metadata?.test_framework ?? "—"} />
                    <Row label="Files" value={String(metadata?.file_count ?? 0)} />
                    <Row label="Status" value={<Badge tone="muted">{project.status}</Badge>} />
                  </div>
                </Panel>
                <Panel>
                  <PanelHeader
                    title="Latest run"
                    icon={<FlaskConical className="h-4 w-4" />}
                    subtitle={record ? formatRelative(record.created_at) : "not run yet"}
                  />
                  <div className="p-4">
                    {record?.test_result ? (
                      <TestRunSummary run={record.test_result} />
                    ) : record?.api_result ? (
                      <div className="space-y-2 text-xs">
                        <p className="text-muted">{record.label}</p>
                        <ul className="space-y-1">
                          {record.api_result.probes.slice(0, 8).map((probe, index) => (
                            <li key={index} className="flex items-center gap-2">
                              <Badge tone={statusCodeTone(probe.status_code)}>
                                {probe.status_code ?? "ERR"}
                              </Badge>
                              <span className="mono truncate text-muted">
                                {probe.method} {probe.path}
                              </span>
                              <span className="ml-auto shrink-0 text-faint">
                                {probe.latency_ms}ms
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <EmptyState
                        title="Nothing run yet"
                        description="Run the test suite or probe the API to detect failures."
                      />
                    )}
                  </div>
                </Panel>
              </div>

              <Panel>
                <PanelHeader
                  title="Discovered API surface"
                  subtitle={`${metadata?.routes.length ?? 0} route(s) found by static analysis`}
                  icon={<RouteIcon className="h-4 w-4" />}
                />
                {metadata?.routes.length ? (
                  <div className="scroll-thin max-h-72 overflow-y-auto">
                    <table className="w-full text-xs">
                      <tbody className="divide-y divide-line">
                        {metadata.routes.map((route) => (
                          <tr key={`${route.method}-${route.path}`} className="hover:bg-elevated/50">
                            <td className="w-20 px-4 py-2">
                              <Badge tone="accent">{route.method}</Badge>
                            </td>
                            <td className="mono px-2 py-2 text-ink">{route.path}</td>
                            <td className="mono px-2 py-2 text-right text-faint">
                              {route.file}:{route.line}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState title="No routes discovered" description="Run Analyze to re-scan the workspace." />
                )}
              </Panel>

              {metadata?.notes.length ? (
                <Panel>
                  <PanelHeader title="Analyzer notes" />
                  <ul className="space-y-1 p-4 text-xs text-muted">
                    {metadata.notes.map((note, index) => (
                      <li key={index}>• {note}</li>
                    ))}
                  </ul>
                </Panel>
              ) : null}
            </>
          ) : null}

          {tab === "failures" ? (
            <>
              {!failures.length ? (
                <Panel>
                  <EmptyState
                    icon={<Bug className="h-7 w-7" />}
                    title="No failures detected"
                    description="Run the test suite or probe the API. Failures found there appear here with their normalized error, file and line."
                    action={
                      <Button size="sm" loading={busy === "tests"} onClick={onRunTests}>
                        <PlayCircle className="h-3.5 w-3.5" /> Run tests
                      </Button>
                    }
                  />
                </Panel>
              ) : (
                <div className="space-y-3">
                  {failures.map((failure) => (
                    <Panel key={failure.id}>
                      <div className="space-y-3 p-4">
                        <FailureHeader failure={failure} />
                        <div className="flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            loading={busy === "diagnose"}
                            disabled={busy !== null}
                            onClick={() => onDiagnose(failure.id)}
                          >
                            <Stethoscope className="h-3.5 w-3.5" />
                            {busy === "diagnose" ? "Analyzing API response…" : "Diagnose"}
                          </Button>
                          <Button
                            size="sm"
                            variant="primary"
                            disabled={running || busy !== null}
                            loading={busy === "repair"}
                            onClick={() => onRepair(failure.id)}
                          >
                            <Wrench className="h-3.5 w-3.5" />
                            {busy === "repair" ? "Starting repair…" : "Repair this failure"}
                          </Button>
                        </div>
                        {failure.traceback ? (
                          <details>
                            <summary className="cursor-pointer text-2xs text-muted hover:text-ink">
                              Stack trace
                            </summary>
                            <pre className="mono scroll-thin mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded border border-line bg-canvas p-2.5 text-2xs text-muted">
                              {failure.traceback}
                            </pre>
                          </details>
                        ) : null}
                      </div>
                    </Panel>
                  ))}
                </div>
              )}

              {diagnosis ? (
                <Panel>
                  <PanelHeader
                    title="Diagnosis"
                    subtitle="Read-only investigation — nothing was written to your files"
                    icon={<Stethoscope className="h-4 w-4" />}
                  />
                  <div className="space-y-4 p-4">
                    {diagnosis.note ? (
                      <p className="rounded border border-line bg-elevated p-2 text-2xs text-muted">
                        {diagnosis.note}
                      </p>
                    ) : null}
                    <DiagnosisPanel
                      diagnosis={diagnosis.diagnosis}
                      failure={diagnosis.failure}
                      observedFacts={diagnosis.facts}
                    />
                  </div>
                </Panel>
              ) : null}

              {record?.test_result ? (
                <Panel>
                  <PanelHeader title="Test output" />
                  <div className="space-y-3 p-4">
                    <FailingTestList run={record.test_result} />
                    <TestOutput run={record.test_result} />
                  </div>
                </Panel>
              ) : null}
            </>
          ) : null}

          {tab === "repair" ? (
            session ? (
              <RepairSessionView
                session={session}
                running={running}
                onChanged={() => {
                  void refreshActive();
                  void refreshProject();
                  void refreshExecution();
                }}
              />
            ) : (
              <Panel>
                <EmptyState
                  icon={<Wrench className="h-7 w-7" />}
                  title="No repair session yet"
                  description="Detect a failure first, then start a repair. The agent will investigate, propose a minimal patch for your approval, apply it, and verify the result against the real test suite."
                  action={
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={!failures.length}
                      loading={busy === "repair"}
                      onClick={() => onRepair(failures[0]?.id)}
                    >
                      <Wrench className="h-3.5 w-3.5" /> Start repair
                    </Button>
                  }
                />
              </Panel>
            )
          ) : null}

          {tab === "history" ? <TestHistory projectId={projectId} /> : null}

          {tab === "code" ? <CodeBrowser projectId={projectId} /> : null}
        </div>

        <Panel className="flex h-[calc(100vh-13rem)] flex-col xl:sticky xl:top-6">
          <ActivityStream
            events={events}
            connected={connected}
            className="flex-1"
            emptyHint="Run tests or start a repair to watch each agent step stream in."
          />
        </Panel>
      </div>
    </div>
  );
}

function CodeBrowser({ projectId }: { projectId: string }) {
  const [selected, setSelected] = React.useState<string | null>(null);
  const [file, setFile] = React.useState<FileContent | null>(null);
  const [loading, setLoading] = React.useState(false);
  const { data: tree } = useAsync(() => getProjectFiles(projectId), [projectId]);

  React.useEffect(() => {
    if (!selected) return;
    setLoading(true);
    getProjectFile(projectId, selected)
      .then(setFile)
      .catch(() => setFile(null))
      .finally(() => setLoading(false));
  }, [projectId, selected]);

  return (
    <Panel className="overflow-hidden">
      <PanelHeader
        title="Workspace"
        subtitle={selected ?? "Browse the project source"}
        icon={<FileCode2 className="h-4 w-4" />}
      />
      <div className="grid h-[600px] grid-cols-1 md:grid-cols-[240px_1fr]">
        <div className="border-b border-line md:border-b-0 md:border-r">
          <FileTree
            nodes={tree?.tree ?? []}
            selected={selected}
            onSelect={setSelected}
            className="h-full max-h-[600px]"
          />
        </div>
        <CodeView file={file} loading={loading} className="h-full max-h-[600px]" />
      </div>
    </Panel>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted">{label}</span>
      <span className={mono ? "mono truncate text-ink" : "text-ink"}>{value}</span>
    </div>
  );
}
