import type { ApiError, AssistantEvent, AssistantInfo, ChatTurn, JobParams, JobResult, JobStatus, Project, Run, ValidationResult } from "@/types";

// VITE_API_BASE must point at the production API in Vercel builds. Empty means same origin (Vite dev proxy).
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export const url = (path: string) => (path.startsWith("http") ? path : `${API_BASE}${path}`);

export class CanopyApiError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) {
    const b = body as Partial<ApiError> & { detail?: string };
    throw new CanopyApiError(
      b?.error_code ?? `http_${res.status}`,
      b?.error_message ?? b?.detail ?? `The server returned an error (${res.status}). Please try again.`,
    );
  }
  return body as T;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url(path), init);
  } catch {
    throw new CanopyApiError(
      "network",
      "Could not reach the analysis server. The free demo instance may be waking up; please try again in a few seconds.",
    );
  }
  return parse<T>(res);
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  // projects
  projects: () => request<{ projects: Project[] }>("/api/projects").then((r) => r.projects),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  inspectFile: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ kind: string; areas: { index: number; name: string | null }[] }>("/api/uploads/inspect", { method: "POST", body: form });
  },
  createFromFile: (name: string, file: File, selection?: number[], params?: Partial<JobParams>) => {
    const form = new FormData();
    form.append("name", name);
    form.append("file", file);
    form.append("params", JSON.stringify(params ?? {}));
    if (selection) form.append("selection", JSON.stringify(selection));
    return request<{ project: Project; run: Run | null }>("/api/projects", { method: "POST", body: form });
  },
  createFromArea: (name: string, aoi: GeoJSON.Polygon, params?: Partial<JobParams>) =>
    request<{ project: Project; run: Run | null }>("/api/projects", json("POST", { name, aoi, params: params ?? {} })),
  createFromSample: (name: string) =>
    request<{ project: Project; run: Run | null }>("/api/projects", json("POST", { name, template: "sample" })),
  renameProject: (id: string, name: string) => request<Project>(`/api/projects/${id}`, json("PATCH", { name })),
  deleteProject: (id: string) => request<null>(`/api/projects/${id}`, { method: "DELETE" }),
  startRun: (id: string, params: JobParams) => request<Run>(`/api/projects/${id}/runs`, json("POST", { params })),

  // runs (a run id is a job id)
  status: (jobId: string) => request<JobStatus>(`/api/jobs/${jobId}`),
  result: (jobId: string) => request<JobResult>(`/api/jobs/${jobId}/result`),
  crowns: (result: JobResult) => request<GeoJSON.FeatureCollection>(result.crowns_geojson_url),
  rejected: (result: JobResult) => request<GeoJSON.FeatureCollection>(result.rejected_geojson_url),
  validate: (jobId: string, bbox: [number, number, number, number], clicks: [number, number][]) =>
    request<ValidationResult>(`/api/jobs/${jobId}/validate`, json("POST", { bbox, clicks })),

  // workspace assistant
  assistantInfo: (projectId: string) => request<AssistantInfo>(`/api/projects/${projectId}/assistant`),
  chat: (projectId: string, runId: string | null, messages: ChatTurn[], onEvent: (e: AssistantEvent) => void, signal?: AbortSignal) =>
    streamChat(projectId, runId, messages, onEvent, signal),
};

/** POSTs the conversation and reads the Server-Sent Events stream until it ends. */
async function streamChat(
  projectId: string,
  runId: string | null,
  messages: ChatTurn[],
  onEvent: (e: AssistantEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(url(`/api/projects/${projectId}/assistant/chat`), { ...json("POST", { messages, run_id: runId }), signal });
  } catch {
    if (signal?.aborted) return;
    throw new CanopyApiError("network", "Could not reach the analysis server.");
  }
  if (!res.ok || !res.body) await parse(res);
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      for (const line of frame.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)) as AssistantEvent);
          } catch {
            /* a malformed frame is skipped, not fatal */
          }
        }
      }
    }
  }
}
