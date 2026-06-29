import { useQuery } from "@tanstack/react-query";
import { fetchSession } from "@/lib/sessions-api";

/** FR-05 / AC-05 — single session detail from API */
export function useSessionDetail(sessionId: string | undefined) {
  return useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => fetchSession(sessionId!),
    enabled: Boolean(sessionId),
    refetchInterval: 30_000,
  });
}
