"use client";

import {
  ArrowLeft,
  Bug,
  Download,
  FileCode2,
  FlaskConical,
  Globe,
  History,
  LayoutGrid,
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
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  IconTile,
  KeyValue,
  LinkButton,
  Spinner,
  Tabs,
} from "@/components/ui/primitives";
import { useAsync, useEvents, usePolling } from "@/hooks/useEvents";
import {
  analyzeProject,
  diagnose,
  exportProjectUrl,
  getActiveRepair,
  getProject,
  getProjectFile,
  getProjectFiles,
  latestExecution,
  probeApi,
  runTests,
  startRepair,
} from "@/lib/api";
import { formatRelative, statusCodeTone } from "@/lib/utils";
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
  const [diagnosis, setDiagnosis] = React.useState<{
    failure: NormalizedFailure;
    diagnosis: DiagnosisResult;
    facts: string[];
    note: string;
  } | null>(null);

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
  const failures = record
    ? (record.test_result?.failures ?? record.api_result?.failures ?? [])
    : [];
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
    <div className="space-y-5 animate-fade-up">
      {/* --------------------------------------------------------- header */}
      <header className="space-y-4">
        <Link
          href="/projects"
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted transition-colors hover:text-brand-ink"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> All projects
        </Link>

        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="truncate text-2xl font-bold tracking-tight text-ink">
                {project.name}
              </h1>
              <Badge tone="muted">{project.status}</Badge>
            </div>
            <p className="mt-1 truncate text-sm text-muted">
              {project.description ?? project.origin ?? project.source}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              loading={busy === "analyze"}
              disabled={busy !== null}
              onClick={onAnalyze}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              {busy === "analyze" ? "Analysing…" : "Analyse"}
            </Button>
            <Button
              size="sm"
              loading={busy === "tests"}
              disabled={busy !== null}
              onClick={onRunTests}
            >
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
            <LinkButton
              href={exportProjectUrl(projectId)}
              download
              size="sm"
              variant="secondary"
              title="Download the project workspace as a ZIP archive"
            >
              <Download className="h-3.5 w-3.5" />
              Export ZIP
            </LinkButton>
          </div>
        </div>
      </header>

      {error ? <ErrorNote message={error} /> : null}

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview", icon: <LayoutGrid className="h-3.5 w-3.5" /> },
          {
            id: "failures",
            label: "Failures",
            count: failures.length,
            icon: <Bug className="h-3.5 w-3.5" />,
          },
          {
            id: "repair",
            label: "Repair",
            count: session ? session.attempts.length : undefined,
            icon: <Wrench className="h-3.5 w-3.5" />,
          },
          { id: "history", label: "History", icon: <History className="h-3.5 w-3.5" /> },
          { id: "code", label: "Code", icon: <FileCode2 className="h-3.5 w-3.5" /> },
        ]}
      />

      <div className="grid gap-5 xl:grid-cols-[1fr_22rem]">
        <div className="min-w-0 space-y-5">
          {/* ------------------------------------------------------ overview */}
          {tab === "overview" ? (
            <>
              <div className="grid gap-4 lg:grid-cols-2">
                <Card>
                  <CardHeader
                    title="Project"
                    icon={
                      <IconTile tone="brand" size="sm">
                        <Stethoscope className="h-3.5 w-3.5" />
                      </IconTile>
                    }
                  />
                  <div className="p-4">
                    <KeyValue label="Language">{metadata?.language ?? "—"}</KeyValue>
                    <KeyValue label="Framework">{metadata?.framework ?? "—"}</KeyValue>
                    <KeyValue label="Entry point" mono>
                      {metadata?.entry_point ?? "—"}
                    </KeyValue>
                    <KeyValue label="Test framework">{metadata?.test_framework ?? "—"}</KeyValue>
                    <KeyValue label="Files">{String(metadata?.file_count ?? 0)}</KeyValue>
                    <KeyValue label="Routes">{String(metadata?.routes.length ?? 0)}</KeyValue>
                  </div>
                </Card>

                <Card>
                  <CardHeader
                    title="Latest run"
                    subtitle={record ? formatRelative(record.created_at) : "not run yet"}
                    icon={
                      <IconTile tone="info" size="sm">
                        <FlaskConical className="h-3.5 w-3.5" />
                      </IconTile>
                    }
                  />
                  <div className="p-4">
                    {record?.test_result ? (
                      <TestRunSummary run={record.test_result} />
                    ) : record?.api_result ? (
                      <div className="space-y-2.5">
                        <p className="break-words text-xs leading-relaxed text-muted [overflow-wrap:anywhere]">
                          {record.label}
                        </p>
                        <ul className="space-y-1.5">
                          {record.api_result.probes.slice(0, 8).map((probe, index) => (
                            <li key={index} className="flex items-center gap-2 text-xs">
                              <Badge tone={statusCodeTone(probe.status_code)}>
                                {probe.status_code ?? "ERR"}
                              </Badge>
                              <span className="mono truncate text-muted">
                                {probe.method} {probe.path}
                              </span>
                              <span className="ml-auto shrink-0 tabular-nums text-faint">
                                {probe.latency_ms}ms
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <EmptyState
                        icon={<PlayCircle className="h-5 w-5" />}
                        title="Nothing run yet"
                        description="Run the test suite or probe the API to detect failures."
                        action={
                          <Button size="sm" loading={busy === "tests"} onClick={onRunTests}>
                            Run tests
                          </Button>
                        }
                      />
                    )}
                  </div>
                </Card>
              </div>

              <Card className="overflow-hidden">
                <CardHeader
                  title="Discovered API surface"
                  subtitle={`${metadata?.routes.length ?? 0} route(s) found by static analysis`}
                  icon={
                    <IconTile tone="grape" size="sm">
                      <RouteIcon className="h-3.5 w-3.5" />
                    </IconTile>
                  }
                />
                {metadata?.routes.length ? (
                  <div className="scroll-thin max-h-80 overflow-auto">
                    <table className="w-full text-xs">
                      <tbody className="divide-y divide-line">
                        {metadata.routes.map((route) => (
                          <tr
                            key={`${route.method}-${route.path}`}
                            className="transition-colors hover:bg-brand-soft/40"
                          >
                            <td className="w-24 px-4 py-2.5">
                              <Badge tone="brand">{route.method}</Badge>
                            </td>
                            <td className="mono px-2 py-2.5 font-medium text-ink">{route.path}</td>
                            <td className="mono px-4 py-2.5 text-right text-2xs text-faint">
                              {route.file}:{route.line}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState
                    icon={<RouteIcon className="h-5 w-5" />}
                    title="No routes discovered"
                    description="Run Analyse to re-scan the workspace."
                  />
                )}
              </Card>

              {metadata?.notes.length ? (
                <Card>
                  <CardHeader title="Analyser notes" />
                  <ul className="space-y-1.5 p-4 text-xs text-muted">
                    {metadata.notes.map((note, index) => (
                      <li key={index} className="flex gap-2">
                        <span className="text-brand" aria-hidden>
                          ›
                        </span>
                        <span className="min-w-0">{note}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              ) : null}
            </>
          ) : null}

          {/* ------------------------------------------------------ failures */}
          {tab === "failures" ? (
            <>
              {!failures.length ? (
                <Card>
                  <EmptyState
                    icon={<Bug className="h-5 w-5" />}
                    title="No failures detected"
                    description="Run the test suite or probe the API. Failures found there appear here with their normalised error, file and line."
                    action={
                      <Button variant="primary" loading={busy === "tests"} onClick={onRunTests}>
                        <PlayCircle className="h-4 w-4" /> Run tests
                      </Button>
                    }
                  />
                </Card>
              ) : (
                <div className="space-y-3">
                  {failures.map((failure) => (
                    <Card key={failure.id} className="border-l-4 border-l-danger">
                      <div className="space-y-4 p-4">
                        <FailureHeader failure={failure} />
                        <div className="flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            loading={busy === "diagnose"}
                            disabled={busy !== null}
                            onClick={() => onDiagnose(failure.id)}
                          >
                            <Stethoscope className="h-3.5 w-3.5" />
                            {busy === "diagnose" ? "Investigating…" : "Diagnose"}
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
                          <details className="overflow-hidden rounded-xl border border-line">
                            <summary className="cursor-pointer bg-elevated/60 px-3.5 py-2 text-2xs font-semibold text-muted transition-colors hover:text-ink">
                              Stack trace
                            </summary>
                            <pre className="mono scroll-thin max-h-72 overflow-auto whitespace-pre-wrap border-t border-line bg-sunken p-3 text-2xs leading-relaxed text-muted">
                              {failure.traceback}
                            </pre>
                          </details>
                        ) : null}
                      </div>
                    </Card>
                  ))}
                </div>
              )}

              {diagnosis ? (
                <Card>
                  <CardHeader
                    title="Diagnosis"
                    subtitle="Read-only investigation — nothing was written to your files"
                    icon={
                      <IconTile tone="brand" size="sm">
                        <Stethoscope className="h-3.5 w-3.5" />
                      </IconTile>
                    }
                  />
                  <div className="space-y-4 p-4">
                    {diagnosis.note ? (
                      <p className="rounded-lg border border-line bg-sunken px-3 py-2 text-2xs text-muted">
                        {diagnosis.note}
                      </p>
                    ) : null}
                    <DiagnosisPanel
                      diagnosis={diagnosis.diagnosis}
                      failure={diagnosis.failure}
                      observedFacts={diagnosis.facts}
                    />
                  </div>
                </Card>
              ) : null}

              {record?.test_result ? (
                <Card>
                  <CardHeader title="Test output" />
                  <div className="space-y-3 p-4">
                    <FailingTestList run={record.test_result} />
                    <TestOutput run={record.test_result} />
                  </div>
                </Card>
              ) : null}
            </>
          ) : null}

          {/* -------------------------------------------------------- repair */}
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
              <Card>
                <EmptyState
                  icon={<Wrench className="h-5 w-5" />}
                  title="No repair session yet"
                  description="Detect a failure first, then start a repair. The agent will investigate, propose a minimal patch for your approval, apply it, and verify the result against the real test suite."
                  action={
                    <Button
                      variant="primary"
                      disabled={!failures.length}
                      loading={busy === "repair"}
                      onClick={() => onRepair(failures[0]?.id)}
                    >
                      <Wrench className="h-4 w-4" /> Start repair
                    </Button>
                  }
                />
              </Card>
            )
          ) : null}

          {tab === "history" ? <TestHistory projectId={projectId} /> : null}

          {tab === "code" ? <CodeBrowser projectId={projectId} /> : null}
        </div>

        {/* ------------------------------------------------------- live feed */}
        <Card className="flex h-[calc(100vh-9rem)] max-h-[44rem] min-h-[26rem] flex-col overflow-hidden xl:sticky xl:top-20">
          <ActivityStream
            events={events}
            connected={connected}
            emptyHint="Run tests or start a repair to watch each agent step stream in."
          />
        </Card>
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
    <Card className="overflow-hidden">
      <CardHeader
        title="Workspace"
        subtitle={selected ?? "Browse the project source"}
        icon={
          <IconTile tone="info" size="sm">
            <FileCode2 className="h-3.5 w-3.5" />
          </IconTile>
        }
      />
      <div className="grid h-[36rem] grid-cols-1 md:grid-cols-[15rem_1fr]">
        <div className="border-b border-line md:border-b-0 md:border-r">
          <FileTree
            nodes={tree?.tree ?? []}
            selected={selected}
            onSelect={setSelected}
            className="h-full max-h-[36rem]"
          />
        </div>
        <CodeView file={file} loading={loading} className="h-full max-h-[36rem]" />
      </div>
    </Card>
  );
}
