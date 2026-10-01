export const BASE = "/api";

let onUnauthorized: (() => void) | null = null;
export function setOnUnauthorized(cb: () => void) {
  onUnauthorized = cb;
}

/** An HTTP failure that kept its status code.
 *
 * Callers need to tell "this resource is gone" (404 → show the not-found page)
 * from "something broke" (500 → show the error). The message keeps the
 * `"<status>: <body>"` shape the UI already strips a prefix from, so existing
 * error rendering is unaffected.
 */
export class ApiError extends Error {
  // Declared explicitly rather than as a constructor parameter property:
  // tsconfig sets erasableSyntaxOnly, which disallows the shorthand.
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** True when `err` is a 404 from the API. */
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

/** POST/PATCH/DELETE helpers keep the same error shape as `http`. */
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

/** For endpoints whose 2xx body carries no payload — resolves undefined. */
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

/** Trigger a browser download for a GET endpoint that sets Content-Disposition. */
export function downloadFile(url: string) {
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
