/**
 * Typed client for the API Doctor backend.
 *
 * Requests go to a same-origin `/api` path, which Next rewrites to the FastAPI
 * server (see next.config.mjs). The OpenAI key lives only on the backend and is
 * never fetched, stored or displayed here.
 */

import type { AuthUser } from "@/lib/auth";
import type {
  DiagnosisResult,
  ExecutionRecord,
  FileContent,
  FileNode,
  Investigation,
  InvestigationReport,
  NormalizedFailure,
  Project,
  ProjectSummary,
  RepairSession,
  RepairSessionSummary,
  RouteInfo,
  SessionInfo,
  SystemInfo,
  UserPreferences,
} from "@/types";

export const API_BASE = "/api";

export class ApiError extends Error {
  status: number;
  detail: string;
  /** Which form input the backend blamed, when it named one. */
  field: string | null;

  constructor(status: number, detail: string, field: string | null = null) {
    super(detail || `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.field = field;
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
    // Carries the HttpOnly session cookie. Without it every authenticated
    // request would look anonymous to the backend.
    credentials: "include",
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body?.detail ?? JSON.stringify(body);
    } catch {
      try {
        detail = (await response.text()) || detail;
      } catch {
        /* keep statusText */
      }
    }
    throw new ApiError(response.status, detail, response.headers.get("X-Field"));
  }

  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return (await response.text()) as unknown as T;
  }
  return (await response.json()) as T;
}

/* ------------------------------------------------------------- system --- */

export const getHealth = () => request<{ status: string }>("/health");
export const getSystem = () => request<SystemInfo>("/system");
export const getSandbox = () =>
  request<{
    kind: string;
    isolated: boolean;
    network: string;
    description: string;
    warnings: string[];
    limits: Record<string, unknown>;
    trusted_mode_banner: string | null;
  }>("/execution/sandbox");

/* ----------------------------------------------------------- projects --- */

export const listProjects = () => request<ProjectSummary[]>("/projects");
export const getProject = (id: string) => request<Project>(`/projects/${id}`);
export const deleteProject = (id: string) =>
  request<{ deleted: boolean }>(`/projects/${id}`, { method: "DELETE" });
export const analyzeProject = (id: string) =>
  request<Project>(`/projects/${id}/analyze`, { method: "POST" });
export const getProjectFiles = (id: string) =>
  request<{ tree: FileNode[] }>(`/projects/${id}/files`);
export const getProjectFile = (id: string, path: string) =>
  request<FileContent>(`/projects/${id}/file?path=${encodeURIComponent(path)}`);
export const getProjectRoutes = (id: string) =>
  request<{ routes: RouteInfo[]; framework: string; entry_point: string | null }>(
    `/projects/${id}/routes`,
  );

export async function uploadProject(file: File, name?: string): Promise<Project> {
  const form = new FormData();
  form.append("file", file);
  if (name) form.append("name", name);
  return request<Project>("/projects/upload", { method: "POST", body: form });
}

/* ---------------------------------------------------------- execution --- */

export const runTests = (id: string) =>
  request<ExecutionRecord>(`/execution/${id}/tests`, { method: "POST" });
export const probeApi = (id: string) =>
  request<ExecutionRecord>(`/execution/${id}/probe`, { method: "POST" });
export const executionHistory = (id: string) =>
  request<ExecutionRecord[]>(`/execution/${id}/history`);
export const latestExecution = (id: string) =>
  request<{ record: ExecutionRecord | null }>(`/execution/${id}/latest`);

/* ---------------------------------------------------------- diagnosis --- */

export const diagnose = (id: string, failureId?: string) =>
  request<{
    project_id: string;
    failure: NormalizedFailure;
    diagnosis: DiagnosisResult;
    investigation: Investigation | null;
    observed_facts: string[];
    reasoning_engine: string;
    note: string;
  }>(`/diagnosis/${id}`, {
    method: "POST",
    body: JSON.stringify({ failure_id: failureId ?? null }),
  });

/* ------------------------------------------------------------- repair --- */

export const startRepair = (
  id: string,
  options: { mode?: "test" | "api"; failure_id?: string | null; auto_approve?: boolean | null } = {},
) =>
  request<RepairSession>(`/repair/${id}/start`, {
    method: "POST",
    body: JSON.stringify({
      mode: options.mode ?? "test",
      failure_id: options.failure_id ?? null,
      auto_approve: options.auto_approve ?? null,
    }),
  });

export const getActiveRepair = (id: string) =>
  request<{ running: boolean; session: RepairSession | null }>(`/repair/${id}/active`);

export const decidePatch = (
  projectId: string,
  patchId: string,
  approve: boolean,
  note?: string,
) =>
  request<{ approved: boolean }>(`/repair/${projectId}/patch/${patchId}/decision`, {
    method: "POST",
    body: JSON.stringify({ approve, note: note ?? null }),
  });

export const cancelRepair = (id: string) =>
  request<{ cancelled: boolean }>(`/repair/${id}/cancel`, { method: "POST" });

export const listSessions = (projectId: string) =>
  request<RepairSessionSummary[]>(`/repair/${projectId}/sessions`);

export const getSession = (projectId: string, sessionId: string) =>
  request<RepairSession>(`/repair/${projectId}/sessions/${sessionId}`);

export const rollbackSession = (projectId: string, sessionId: string) =>
  request<{ rolled_back: boolean; files: string[] }>(
    `/repair/${projectId}/sessions/${sessionId}/rollback`,
    { method: "POST" },
  );

/* ------------------------------------------------------------ reports --- */

export const getReport = (sessionId: string) =>
  request<InvestigationReport>(`/reports/sessions/${sessionId}`);
export const reportMarkdownUrl = (sessionId: string) =>
  `${API_BASE}/reports/sessions/${sessionId}/markdown`;

/* ------------------------------------------------------------ account --- */

export const updateProfile = (name: string) =>
  request<AuthUser>("/account/profile", {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });

export const changePassword = (currentPassword: string, newPassword: string) =>
  request<{ status: string; detail: string }>("/account/password", {
    method: "POST",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });

export const listActiveSessions = () =>
  request<{ sessions: SessionInfo[]; count: number }>("/account/sessions");

export const revokeAllSessions = () =>
  request<{ status: string; revoked: number }>("/account/sessions/revoke-all", {
    method: "POST",
  });

export const getPreferences = () => request<UserPreferences>("/account/preferences");

/** A partial update: fields left out keep their stored value. */
export const updatePreferences = (changes: Partial<UserPreferences>) =>
  request<UserPreferences>("/account/preferences", {
    method: "PUT",
    body: JSON.stringify(changes),
  });

export const deleteAccount = (password: string) =>
  request<{ status: string; projects_deleted: number }>("/account", {
    method: "DELETE",
    body: JSON.stringify({ password }),
  });

/* ------------------------------------------------------------- events --- */

export function eventStreamUrl(projectId?: string, sessionId?: string): string {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (sessionId) params.set("session_id", sessionId);
  const query = params.toString();
  return `${API_BASE}/events${query ? `?${query}` : ""}`;
}
