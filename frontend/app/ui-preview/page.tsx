"use client";

/* TEMPORARY design-review harness — delete after screenshots. */

import { Bug, Cpu, FolderKanban, Route, ShieldCheck, Wrench } from "lucide-react";
import * as React from "react";

import { ActivityStream } from "@/components/agent-activity/activity-stream";
import { AuthProvider } from "@/components/auth/auth-context";
import { DiffView } from "@/components/diff-viewer/diff-view";
import { AppShell } from "@/components/layout/app-shell";
import { ProjectTable } from "@/components/projects/project-table";
import { BeforeAfter, FailingTestList, TestRunSummary } from "@/components/test-results/test-results";
import { ClaimTag, VerdictBanner } from "@/components/ui/claim-ladder";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  Field,
  IconTile,
  Input,
  PageHeader,
  Progress,
  Section,
  Select,
  SettingRow,
  StatTile,
  Tabs,
  Toggle,
} from "@/components/ui/primitives";
import type { AgentEvent, ProjectSummary, TestRunResult } from "@/types";

const RUN_BEFORE: TestRunResult = {
  exit_code: 1,
  passed: 3,
  failed: 1,
  errors: 0,
  skipped: 0,
  total: 4,
  duration_ms: 1840,
  stdout: "collected 4 items\ntests/test_orders.py ...F",
  stderr: "",
  runner: "local",
  timed_out: false,
  collection_error: null,
  cases: [
    { node_id: "tests/test_orders.py::test_order_total", outcome: "failed", duration_ms: 12, message: "TypeError: unsupported operand" },
  ],
  failures: [],
};

const RUN_AFTER: TestRunResult = { ...RUN_BEFORE, exit_code: 0, passed: 4, failed: 0, cases: [] };

const PROJECTS: ProjectSummary[] = [
  {
    id: "1", name: "orders-api", source: "upload", status: "failing",
    created_at: new Date().toISOString(), updated_at: new Date(Date.now() - 6e5).toISOString(),
    language: "python", framework: "FastAPI", route_count: 18, test_count: 24,
    stats: { failures_detected: 3, repairs_attempted: 2, repairs_verified: 1 },
  },
  {
    id: "2", name: "billing-service", source: "upload", status: "repaired",
    created_at: new Date().toISOString(), updated_at: new Date(Date.now() - 36e5).toISOString(),
    language: "python", framework: "Flask", route_count: 9, test_count: 11,
    stats: { failures_detected: 1, repairs_attempted: 1, repairs_verified: 1 },
  },
  {
    id: "3", name: "inventory", source: "upload", status: "repairing",
    created_at: new Date().toISOString(), updated_at: new Date(Date.now() - 12e4).toISOString(),
    language: "python", framework: "Django", route_count: 31, test_count: 40,
    stats: { failures_detected: 2, repairs_attempted: 1, repairs_verified: 0 },
  },
];

const EVENTS: AgentEvent[] = [
  { id: 1, type: "execution.started", level: "info", message: "Running pytest in the workspace sandbox.", at: new Date().toISOString(), data: {} },
  { id: 2, type: "failure.detected", level: "error", message: "TypeError in app/services/orders.py:47 — unsupported operand 'NoneType' and 'int'.", at: new Date().toISOString(), data: {} },
  { id: 3, type: "agent.tool_call", level: "debug", message: "read_file(app/services/orders.py, lines 30-60)", at: new Date().toISOString(), attempt: 1, data: {} },
  { id: 4, type: "diagnosis.ready", level: "info", message: "Root cause established with 0.86 confidence.", at: new Date().toISOString(), attempt: 1, data: {} },
  { id: 5, type: "patch.awaiting_approval", level: "warning", message: "A 1-line patch is waiting for your approval.", at: new Date().toISOString(), attempt: 1, data: {} },
  { id: 6, type: "verification.passed", level: "success", message: "Suite re-run after the patch: 4 passed, 0 failed, exit 0.", at: new Date().toISOString(), attempt: 1, data: {} },
];

const DIFF = `--- a/app/services/orders.py
+++ b/app/services/orders.py
@@ -45,7 +45,7 @@ def order_total(order):
     total = 0
     for item in order.items:
         qty = item.quantity
-        total += item.price * qty
+        total += (item.price or 0) * qty
     return total
`;

export default function UiPreview() {
  const [tab, setTab] = React.useState("overview");
  const [on, setOn] = React.useState(true);

  return (
    <AuthProvider>
      <AppShell>
        <div className="space-y-8">
          <PageHeader
            eyebrow="Design review"
            title="Daylight component gallery"
            description="Every surface the authenticated app is built from, on one page."
            action={<Button variant="primary">Primary action</Button>}
          />

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile label="Projects" value={3} tone="danger" icon={<FolderKanban className="h-3.5 w-3.5" />} hint={<span className="font-semibold text-danger-ink">1 project failing</span>} />
            <StatTile label="API routes" value={58} tone="info" icon={<Route className="h-3.5 w-3.5" />} hint="Discovered by static analysis" />
            <StatTile label="Health index" value="67%" tone="warn" icon={<ShieldCheck className="h-3.5 w-3.5" />} hint={<span className="flex items-center gap-2"><Progress value={0.67} tone="warn" className="h-1.5 flex-1" /><span className="shrink-0 tabular-nums">2/3</span></span>} />
            <StatTile label="Execution" value={<span className="block truncate text-base">Container sandbox</span>} tone="ok" icon={<Cpu className="h-3.5 w-3.5" />} hint="Docker isolated mode" />
          </div>

          <Tabs
            active={tab}
            onChange={setTab}
            tabs={[
              { id: "overview", label: "Overview" },
              { id: "failures", label: "Failures", count: 1, icon: <Bug className="h-3.5 w-3.5" /> },
              { id: "repair", label: "Repair", count: 2, icon: <Wrench className="h-3.5 w-3.5" /> },
              { id: "history", label: "History" },
            ]}
          />

          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">Buttons and badges</h2>
            <Card className="space-y-4 p-4">
              <div className="flex flex-wrap gap-2">
                <Button variant="primary">Primary</Button>
                <Button variant="secondary">Secondary</Button>
                <Button variant="soft">Soft</Button>
                <Button variant="outline">Outline</Button>
                <Button variant="ghost">Ghost</Button>
                <Button variant="success">Success</Button>
                <Button variant="danger">Danger</Button>
                <Button variant="primary" loading>Loading</Button>
                <Button disabled>Disabled</Button>
              </div>
              <div className="flex flex-wrap gap-2">
                {(["ok", "warn", "danger", "info", "brand", "grape", "muted"] as const).map((t) => (
                  <Badge key={t} tone={t}>{t}</Badge>
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                {(["observed", "hypothesis", "root_cause", "proposed_fix", "test_result", "verified"] as const).map((k) => (
                  <ClaimTag key={k} kind={k} />
                ))}
              </div>
              <div className="flex flex-wrap gap-3">
                <IconTile tone="brand"><Wrench className="h-4 w-4" /></IconTile>
                <IconTile tone="ok"><ShieldCheck className="h-4 w-4" /></IconTile>
                <IconTile tone="warn"><Bug className="h-4 w-4" /></IconTile>
                <IconTile tone="grape"><Cpu className="h-4 w-4" /></IconTile>
              </div>
            </Card>
          </section>

          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">Verdicts and alerts</h2>
            <VerdictBanner verified headline="FIX VERIFIED" detail="Your suite was run again after the patch and passed: 4 passed, 0 failed, exit 0." />
            <VerdictBanner verified={false} headline="AWAITING DEVELOPER APPROVAL" detail="A patch is proposed but nothing has been written to your files." />
            <div className="grid gap-3 sm:grid-cols-2">
              <Alert tone="ok" title="Saved">Your preference was stored on your account.</Alert>
              <Alert tone="warn" title="Local trusted mode">Uploaded code runs on the host with no container boundary.</Alert>
              <Alert tone="info" title="Heads up">Write endpoints are skipped unless you opt in.</Alert>
              <ErrorNote message="Could not reach the sandbox runner. Check that Docker is running." />
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">Projects</h2>
            <ProjectTable projects={PROJECTS} />
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader title="Latest run" subtitle="2 minutes ago" icon={<IconTile tone="info" size="sm"><Bug className="h-3.5 w-3.5" /></IconTile>} />
              <div className="space-y-3 p-4">
                <TestRunSummary run={RUN_BEFORE} />
                <FailingTestList run={RUN_BEFORE} />
              </div>
            </Card>
            <Card className="flex h-[26rem] flex-col overflow-hidden">
              <ActivityStream events={EVENTS} connected />
            </Card>
          </section>

          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">Before / after and the diff</h2>
            <BeforeAfter before={RUN_BEFORE} after={RUN_AFTER} />
            <DiffView diff={DIFF} />
          </section>

          <Section title="Settings row" description="How a preference reads." icon={<ShieldCheck className="h-3.5 w-3.5" />}>
            <SettingRow label="AI analysis" hint="When off, results come from the deterministic rule engine only." control={<Toggle label="AI analysis" checked={on} onChange={setOn} />} />
            <SettingRow label="Request timeout" hint="1–300 seconds." control={<div className="flex items-center gap-2"><Input type="number" defaultValue={30} className="w-24" /><span className="text-xs text-muted">sec</span></div>} />
            <SettingRow label="Runner" hint="Where uploaded code executes." control={<Select defaultValue="docker"><option value="docker">Docker</option><option value="local">Local</option></Select>} />
            <div className="px-4 py-4 sm:px-5">
              <div className="max-w-md space-y-4">
                <Field label="Name" htmlFor="p-name" hint="Shown on your account.">
                  <Input id="p-name" defaultValue="Ada Lovelace" />
                </Field>
                <Field label="Email" htmlFor="p-mail" error="That address is already registered.">
                  <Input id="p-mail" defaultValue="ada@example.com" invalid />
                </Field>
              </div>
            </div>
          </Section>

          <Section title="Delete account" tone="danger" description="Permanent. There is no undo.">
            <SettingRow label="Delete this account" hint="Everything you own is removed immediately." control={<Button variant="danger" className="w-full sm:w-auto">Delete account</Button>} />
          </Section>

          <Card>
            <EmptyState
              icon={<Bug className="h-5 w-5" />}
              title="No failures detected"
              description="Run the test suite or probe the API. Failures found there appear here with their normalised error, file and line."
              action={<Button variant="primary">Run tests</Button>}
            />
          </Card>
        </div>
      </AppShell>
    </AuthProvider>
  );
}
