const API_PREFIX = "/api/v1";

function apiBaseUrl(): string {
  // Browser: same-origin relative URLs proxied by Next.js rewrites (see next.config.ts).
  if (typeof window !== "undefined") {
    return "";
  }
  const base =
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:3001";
  return base.replace(/\/$/, "");
}

export class ApiClientError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit & { token?: string },
): Promise<T> {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = `${apiBaseUrl()}${normalizedPath.startsWith(API_PREFIX) ? normalizedPath : `${API_PREFIX}${normalizedPath}`}`;

  const headers = new Headers(init?.headers);
  if (init?.token) {
    headers.set("Authorization", `Bearer ${init.token}`);
  }
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  const response = await fetch(url, { ...init, headers });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    let code: string | undefined;
    try {
      const body = (await response.json()) as { error?: { message?: string; code?: string } };
      message = body.error?.message ?? message;
      code = body.error?.code;
    } catch {
      // Non-JSON error body — keep default message.
    }
    throw new ApiClientError(message, response.status, code);
  }

  return response.json() as Promise<T>;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  db: "connected" | "unavailable";
  requestId: string;
}

export function fetchHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}
