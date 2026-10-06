export const BASE = "/api";

let onUnauthorized: (() => void) | null = null;
export function setOnUnauthorized(cb: () => void) {
  onUnauthorized = cb;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

export async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, init);
  if (!r.ok) {
    if (r.status === 401) onUnauthorized?.();
    throw new ApiError(r.status, `${r.status}: ${await r.text()}`);
  }
  return r.json();
}

export async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const r = await fetch(BASE + path, init);
  if (!r.ok) {
    if (r.status === 401) onUnauthorized?.();
    throw new ApiError(r.status, `${r.status}: ${await r.text()}`);
  }
  if (r.status === 204) return undefined as T;
  return r.json();
}

export const postJson = <T>(path: string, body: unknown): Promise<T> =>
  request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export async function requestVoid(
  path: string,
  init?: RequestInit,
): Promise<void> {
  const r = await fetch(BASE + path, init);
  if (!r.ok) {
    if (r.status === 401) onUnauthorized?.();
    throw new ApiError(r.status, `${r.status}: ${await r.text()}`);
  }
}

export function downloadFile(url: string) {
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
