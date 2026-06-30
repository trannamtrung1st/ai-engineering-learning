import { useQuery } from "@tanstack/react-query";
import { fetchSession } from "@/lib/sessions-api";

export interface UseSessionDetailOptions {
  /** Poll interval in ms — fullscreen presenter uses a faster cadence for live close detection */
  refetchIntervalMs?: number;
}

/** FR-05 / AC-05 — single session detail from API */
export function useSessionDetail(
  sessionId: string | undefined,
  options?: UseSessionDetailOptions,
) {
  return useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => fetchSession(sessionId!),
    enabled: Boolean(sessionId),
    refetchInterval: options?.refetchIntervalMs ?? 30_000,
  });
}
