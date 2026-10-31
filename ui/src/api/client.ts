import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

type Schemas = components["schemas"];
export type AgentInfo = Schemas["AgentInfo"];
export type AgentList = Schemas["AgentList"];
export type AgentResult = Schemas["AgentResult"];
export type Finding = Schemas["Finding"];
export type Evidence = Schemas["Evidence"];
export type Answer = Schemas["Answer"];
export type Choice = Schemas["Choice"];
export type Question = Schemas["Question"];
export type QuestionBatch = Schemas["QuestionBatch"];
export type ProgressEvent = Schemas["ProgressEvent"];
export type RunView = Schemas["RunView"];
export type RunFile = Schemas["RunFile"];
export type Upload = Schemas["Upload"];
export type RunStatus = RunView["status"];
export type JsonSchema = Record<string, unknown>;

// VITE_API_URL="" means the API serves this UI itself (the Docker image): same address.
export const API_URL: string = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

/** Where the API is, for messages: the page's own address when they are served together. */
export const API_LABEL: string = API_URL || globalThis.location?.origin || "this address";

// fetch is looked up per request (not captured once), so tests can stub it
export const api = createClient<paths>({ baseUrl: API_URL, fetch: (request) => globalThis.fetch(request) });

/** The API could not be reached at all (not started, wrong port, CORS). */
export class ApiUnreachable extends Error {
  constructor() {
    super(`Can't reach the API at ${API_LABEL}`);
  }
}

/** The API answered with an error status. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export function errorDetail(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : String(d)))
        .join("; ");
    }
  }
  return fallback;
}

/** Run an openapi-fetch call, turning network failures and error statuses into exceptions. */
export async function call<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let outcome: { data?: T; error?: unknown; response: Response };
  try {
    outcome = await request;
  } catch {
    throw new ApiUnreachable();
  }
  if (outcome.error !== undefined || outcome.data === undefined) {
    throw new ApiError(
      outcome.response.status,
      errorDetail(outcome.error, `${outcome.response.status} ${outcome.response.statusText}`),
    );
  }
  return outcome.data;
}

export const isFinished = (status: RunStatus) => status === "done" || status === "cancelled";

/**
 * Send a file to the API for a run to read; resolves with where it was saved. XHR rather
 * than fetch, because only XHR reports how much of a large upload has been sent.
 */
export function uploadFile(
  file: File,
  onProgress?: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<Upload> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/uploads?name=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = undefined;
      }
      if (xhr.status === 201) resolve(body as Upload);
      else reject(new ApiError(xhr.status, errorDetail(body, `The upload failed (${xhr.status})`)));
    };
    xhr.onerror = () => reject(new ApiUnreachable());
    xhr.onabort = () => reject(new DOMException("The upload was cancelled", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(file);
  });
}

/** Where to download a file a run wrote to its own folder. */
export function runFileUrl(runId: string, name: string): string {
  return `${API_URL}/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(name)}`;
}
