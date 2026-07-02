const DEFAULT_API_ORIGIN = "";

/**
 * Browser calls use same-origin `/api/v1` (Vite dev proxy → API).
 * Override with VITE_API_BASE_URL for direct API origin when CORS is configured.
 */
export function apiOrigin(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  if (typeof configured === "string" && configured.length > 0) {
    return configured.replace(/\/$/, "");
  }
  return DEFAULT_API_ORIGIN;
}

export function apiV1BaseUrl(): string {
  const origin = apiOrigin();
  return origin ? `${origin}/api/v1` : "/api/v1";
}
