const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export interface ApiErrorDetail {
  field: string;
  code: string;
  message: string;
}

export interface ApiErrorBody {
  errorCode?: string;
  message?: string;
  outcome?: string;
  details?: ApiErrorDetail[];
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<{ ok: true; status: number; data: T } | { ok: false; status: number; data: ApiErrorBody }> {
  const headers = new Headers(init?.headers);
  if (init?.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers,
  });

  if (res.status === 204) {
    if (res.ok) {
      return { ok: true, status: res.status, data: undefined as T };
    }
    return { ok: false, status: res.status, data: {} };
  }

  let data: T & ApiErrorBody;
  try {
    data = (await res.json()) as T & ApiErrorBody;
  } catch {
    data = {} as T & ApiErrorBody;
  }
  if (res.ok) {
    return { ok: true, status: res.status, data };
  }
  return { ok: false, status: res.status, data };
}
