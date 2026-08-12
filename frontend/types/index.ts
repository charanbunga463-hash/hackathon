/** Types mirroring the FastAPI backend's Pydantic models. */

export type ProjectSource = "upload";
export type ProjectStatus =
  | "created" | "analyzing" | "ready" | "healthy" | "failing"
  | "repairing" | "repaired" | "error";

export type Severity = "critical" | "high" | "medium" | "low";

export type RepairVerdict =
  | "pending"
  | "no_failure_detected"
  | "awaiting_approval"
  | "verified"
  | "patch_applied_unverified"
  | "repair_failed"
  | "rejected_by_developer"
  | "aborted"
  | "error";

export type RepairStage =
  | "observe" | "investigate" | "diagnose" | "plan" | "generate_patch"
  | "validate_patch" | "await_approval" | "apply" | "verify" | "retry" | "done";

export interface RouteInfo {
  method: string;
  path: string;
  file: string;
  line: number;
  function?: string | null;
  source: "static" | "openapi";
  status_codes: number[];
  parameters: string[];
  request_body?: string | null;
  response_model?: string | null;
  summary?: string | null;
}

export interface TestFileInfo {
  path: string;
  test_count: number;
  test_names: string[];
}

export interface ProjectMetadata {
  language: string;
  framework: string;
  entry_point?: string | null;
  app_object?: string | null;
  test_framework?: string | null;
  test_files: string[];
  test_details: TestFileInfo[];
  routes: RouteInfo[];
  dependencies: { name: string; specifier?: string | null }[];
  source_files: string[];
  config_files: string[];
  has_dockerfile: boolean;
  has_readme: boolean;
  file_count: number;
  total_size_bytes: number;
  notes: string[];
  analyzed_at?: string | null;
}

export interface ProjectStats {
  failures_detected: number;
  repairs_attempted: number;
  repairs_verified: number;
  last_run_at?: string | null;
  last_verdict?: string | null;
}

export interface ProjectSummary {
  id: string;
  name: string;
  source: ProjectSource;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  origin?: string | null;
  language: string;
  framework: string;
  route_count: number;
  test_count: number;
  stats: ProjectStats;
}

export interface Project extends Omit<ProjectSummary, "language" | "framework" | "route_count" | "test_count"> {
  description?: string | null;
  metadata?: ProjectMetadata | null;
  upload_report?: Record<string, unknown> | null;
  error?: string | null;
}

export interface StackFrame {
  file: string;
  line: number;
  function?: string | null;
  code?: string | null;
  in_project: boolean;
}

export interface NormalizedFailure {
  id: string;
  error_type: string;
  message: string;
  file?: string | null;
  line?: number | null;
  function?: string | null;
  test?: string | null;
  endpoint?: string | null;
  status_code?: number | null;
  traceback: string;
  frames: StackFrame[];
  severity: Severity;
  source: "pytest" | "api_probe" | "startup" | "collection";
  detected_at: string;
}

export interface TestCaseResult {
  node_id: string;
  outcome: "passed" | "failed" | "error" | "skipped" | "xfailed" | "xpassed";
  duration_ms: number;
  message: string;
}

export interface TestRunResult {
  exit_code: number;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  total: number;
  duration_ms: number;
  stdout: string;
  stderr: string;
  runner: "docker" | "local";
  timed_out: boolean;
  collection_error?: string | null;
  cases: TestCaseResult[];
  failures: NormalizedFailure[];
}

export interface EndpointProbeResult {
  method: string;
  path: string;
  url: string;
  status_code?: number | null;
  ok: boolean;
  latency_ms: number;
  response_snippet: string;
  error?: string | null;
}

export interface ApiRunResult {
  started: boolean;
  base_url?: string | null;
  startup_error?: string | null;
  openapi?: Record<string, unknown> | null;
  probes: EndpointProbeResult[];
  failures: NormalizedFailure[];
  duration_ms: number;
  runner: "docker" | "local";
}

export interface ExecutionRecord {
  id: string;
  project_id: string;
  mode: "test" | "api";
  created_at: string;
  runner: "docker" | "local";
  isolated: boolean;
  test_result?: TestRunResult | null;
  api_result?: ApiRunResult | null;
  failure_count: number;
  healthy: boolean;
  label: string;
}

export interface EvidenceItem {
  kind: string;
  source: string;
  detail: string;
  line?: number | null;
  excerpt?: string | null;
  verified: boolean;
}

export interface AffectedFile {
  path: string;
  line_start: number;
  line_end: number;
  reason: string;
}

export interface Hypothesis {
  statement: string;
  confidence: number;
  supporting_evidence: string[];
  status: "open" | "supported" | "rejected";
}

export interface DiagnosisResult {
  summary: string;
  root_cause: string;
  confidence: number;
  evidence: EvidenceItem[];
  affected_files: AffectedFile[];
  affected_endpoint?: string | null;
  severity: Severity;
  hypotheses: Hypothesis[];
  failure_id?: string | null;
  reasoning_engine: string;
  grounded: boolean;
  ungrounded_evidence: string[];
  created_at: string;
}

export interface InvestigationStep {
  index: number;
  tool: string;
  arguments: Record<string, unknown>;
  result_summary: string;
  ok: boolean;
  at: string;
}

export interface Investigation {
  failure_id: string;
  steps: InvestigationStep[];
  files_read: string[];
  searches: string[];
  notes: string[];
  engine: string;
  iterations: number;
}

export interface FileEdit {
  path: string;
  operation: "replace" | "insert_after" | "create_file";
  old: string;
  new: string;
  line_hint?: number | null;
  reason: string;
}

export interface PatchProposal {
  id: string;
  project_id: string;
  failure_id?: string | null;
  attempt: number;
  title: string;
  explanation: string;
  edits: FileEdit[];
  tests_to_run: string[];
  risk: string;
  confidence: number;
  status: string;
  reasoning_engine: string;
  created_at: string;
  diff: string;
  stats: Record<string, unknown>;
}

export interface ValidationIssue {
  severity: string;
  code: string;
  message: string;
  path?: string | null;
}

export interface PatchValidation {
  valid: boolean;
  issues: ValidationIssue[];
  files_touched: string[];
  lines_added: number;
  lines_removed: number;
  diff: string;
}

export interface AppliedPatch {
  patch_id: string;
  snapshot_id: string;
  applied_at: string;
  files_changed: string[];
  diff: string;
  rolled_back: boolean;
  rollback_reason?: string | null;
}

export interface VerificationAnalysis {
  verified: boolean;
  verdict_reason: string;
  original_failure_resolved: boolean;
  regressions_introduced: boolean;
  remaining_failures: string[];
  next_action: string;
  retry_guidance: string;
  confidence: number;
  reasoning_engine: string;
}

export interface RepairAttempt {
  attempt: number;
  started_at: string;
  finished_at?: string | null;
  investigation?: Investigation | null;
  diagnosis?: DiagnosisResult | null;
  patch?: PatchProposal | null;
  validation?: PatchValidation | null;
  applied?: AppliedPatch | null;
  targeted_test?: TestRunResult | null;
  full_test?: TestRunResult | null;
  verification?: VerificationAnalysis | null;
  verified: boolean;
  outcome: string;
  failure_reason?: string | null;
  rolled_back: boolean;
}

export interface RepairSession {
  id: string;
  project_id: string;
  project_name: string;
  created_at: string;
  finished_at?: string | null;
  stage: RepairStage;
  verdict: RepairVerdict;
  mode: string;
  reasoning_engine: string;
  execution_runner: string;
  isolated_execution: boolean;
  baseline?: TestRunResult | null;
  baseline_failures: NormalizedFailure[];
  target_failure?: NormalizedFailure | null;
  attempts: RepairAttempt[];
  max_attempts: number;
  require_approval: boolean;
  pending_patch_id?: string | null;
  summary: string;
  error?: string | null;
  duration_ms: number;
}

export interface RepairSessionSummary {
  id: string;
  project_id: string;
  project_name: string;
  created_at: string;
  finished_at?: string | null;
  verdict: RepairVerdict;
  stage: RepairStage;
  attempts: number;
  verified: boolean;
  reasoning_engine: string;
  target?: string | null;
  summary: string;
  duration_ms: number;
}

export interface DashboardStats {
  projects: number;
  failures_detected: number;
  repairs_attempted: number;
  repairs_verified: number;
  repair_success_rate: number;
  average_repair_attempts: number;
  average_repair_seconds: number;
  sessions: number;
  reasoning_engine: string;
  execution_mode: string;
  isolated_execution: boolean;
}

export interface RecentFailure {
  project_id: string;
  project_name: string;
  session_id?: string | null;
  endpoint?: string | null;
  test?: string | null;
  error_type: string;
  message: string;
  status_code?: number | null;
  detected_at: string;
  status: string;
  verdict?: RepairVerdict | null;
}

export interface SystemInfo {
  app_name: string;
  app_env: string;
  ai_provider: string;
  openai_model: string;
  openai_configured: boolean;
  openai_key_hint?: string | null;
  openai_base_url: string;
  reasoning_effort: string;
  max_output_tokens: number;
  agent_max_tool_iterations: number;
  reasoning_engine: string;
  execution_mode_configured: string;
  /** What configuration asks for — not proof that it is available. */
  execution_mode_intended: string;
  /** The runner actually built, after probing the Docker daemon. */
  execution_mode_resolved: string;
  /** True only when a real sandbox probe succeeded. */
  execution_isolated: boolean;
  /** CLI presence only — the daemon may still be down. Use `sandbox.kind` for isolation. */
  docker_cli_present: boolean;
  docker_image: string;
  sandbox_limits: Record<string, unknown>;
  upload_limits: Record<string, number>;
  repair: Record<string, unknown>;
  data_dir: string;
  sandbox?: {
    kind: string;
    isolated: boolean;
    network: string;
    description: string;
    warnings: string[];
  };
}

export interface DashboardResponse {
  stats: DashboardStats;
  recent_failures: RecentFailure[];
  system: SystemInfo;
}

export interface FileNode {
  name: string;
  path: string;
  type: "file" | "directory";
  size: number;
  children?: FileNode[];
}

export interface FileContent {
  path: string;
  content: string;
  lines: number;
  size: number;
  truncated: boolean;
  language: string;
}

export interface InvestigationReport {
  session_id: string;
  project_id: string;
  project_name: string;
  generated_at: string;
  verdict: RepairVerdict;
  verified: boolean;
  headline: string;
  observed_facts: string[];
  hypotheses: string[];
  root_cause?: string | null;
  evidence: EvidenceItem[];
  proposed_fix?: string | null;
  diff?: string | null;
  test_results: {
    attempt: number;
    scope: string;
    summary: string;
    passed: number;
    failed: number;
    total: number;
    exit_code: number;
  }[];
  verification?: VerificationAnalysis | null;
  timeline: { at: string; stage: string; detail: string }[];
  attempts: number;
  reasoning_engine: string;
  execution_runner: string;
  isolated_execution: boolean;
  disclaimer: string;
  markdown: string;
}

export type EventLevel = "info" | "success" | "warning" | "error" | "debug";

export interface AgentEvent {
  id: number;
  type: string;
  level: EventLevel;
  message: string;
  at: string;
  project_id?: string | null;
  session_id?: string | null;
  stage?: string | null;
  attempt?: number | null;
  data: Record<string, any>;
}

export interface HistoryEntry {
  session_id: string;
  project_id: string;
  project_name: string;
  created_at: string;
  finished_at?: string | null;
  verdict: RepairVerdict;
  verified: boolean;
  attempts: number;
  target?: string | null;
  root_cause?: string | null;
  patch_title?: string | null;
  duration_ms: number;
  engine: string;
  summary: string;
}

/* ---------------------------------------------------------------- account -- */

export type Theme = "system" | "light" | "dark";

/**
 * Per-account settings. Every field changes real backend behaviour — see the
 * field comments on `UserPreferences` in backend/app/models/user.py, which name
 * the code that reads each one.
 */
export interface UserPreferences {
  /** Colour scheme for this UI. */
  theme: Theme;
  /** Per-endpoint timeout applied when testing a project's API. */
  api_timeout_seconds: number;
  /** Whether POST/PUT/PATCH/DELETE routes are called during a test run. */
  probe_write_methods: boolean;
  /** When false, analysis uses the deterministic engine and makes no AI call. */
  ai_analysis: boolean;
  /** Whether a proposed patch waits for explicit approval before being applied. */
  require_patch_approval: boolean;
}

/** One live session, as shown on the Settings page. Carries no token. */
export interface SessionInfo {
  /** A truncated digest — a handle for revocation, never a credential. */
  id: string;
  created_at: number;
  last_seen: number;
  expires_at: number;
  user_agent: string;
  /** True for the session making the request. */
  current: boolean;
}
