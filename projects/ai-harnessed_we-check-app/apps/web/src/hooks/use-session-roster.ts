import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSessionRoster } from "@/lib/attendance-roster-api";

/** FR-11 — session attendance roster (no poll; refresh on manual edit) */
export function useSessionRoster(sessionId: string | undefined) {
  return useQuery({
    queryKey: ["session-roster", sessionId],
    queryFn: () => fetchSessionRoster(sessionId!),
    enabled: Boolean(sessionId),
    retry: false,
  });
}

export function useInvalidateSessionRoster() {
  const queryClient = useQueryClient();
  return (sessionId: string) => {
    void queryClient.invalidateQueries({ queryKey: ["session-roster", sessionId] });
    void queryClient.invalidateQueries({ queryKey: ["session-monitor", sessionId] });
  };
}
