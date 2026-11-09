const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) || "/api";
export const TOKEN_KEY = "finovexa_token";

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage can be unavailable in hardened browsers; the in-memory session still works.
  }
}

function extractMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return String(item);
      })
      .join(" · ");
  }
  return fallback;
}

export async function api<T>(
  path: string,
  options: RequestInit & { auth?: boolean } = {},
): Promise<T> {
  const { auth = true, headers, ...rest } = options;
  const token = getToken();
  const requestHeaders = new Headers(headers);
  if (rest.body && !requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }
  if (auth && token) requestHeaders.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...rest, headers: requestHeaders });
  } catch {
    throw new ApiError(
      "The FINOVEXA API could not be reached. Check that the backend is running.",
      0,
    );
  }

  if (response.status === 401 && auth) {
    setToken(null);
    window.dispatchEvent(new CustomEvent("finovexa:unauthorized"));
  }

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => null);

  if (!response.ok) {
    throw new ApiError(
      extractMessage(payload, `Request failed (${response.status}).`),
      response.status,
      payload,
    );
  }
  return payload as T;
}

export function get<T>(
  path: string,
  options: RequestInit & { auth?: boolean } = {},
): Promise<T> {
  return api<T>(path, options);
}

export function post<T>(
  path: string,
  body?: unknown,
  options: RequestInit & { auth?: boolean } = {},
): Promise<T> {
  return api<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
    ...options,
  });
}

export function put<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}) });
}

export function patch<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) });
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { headers });
  } catch {
    throw new ApiError("The file could not be downloaded. Check your connection.", 0);
  }
  if (response.status === 401) {
    setToken(null);
    window.dispatchEvent(new CustomEvent("finovexa:unauthorized"));
  }
  if (!response.ok) {
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json().catch(() => null)
      : await response.text().catch(() => null);
    throw new ApiError(
      extractMessage(payload, `Download failed (${response.status}).`),
      response.status,
      payload,
    );
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const filename = match?.[1] || fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

