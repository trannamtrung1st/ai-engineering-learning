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
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  const data = (await res.json()) as T & ApiErrorBody;
  if (res.ok) {
    return { ok: true, status: res.status, data };
  }
  return { ok: false, status: res.status, data };
}
