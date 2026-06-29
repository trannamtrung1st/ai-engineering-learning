import { useQuery } from "@tanstack/react-query";
import { fetchSessionMonitor } from "@/lib/session-monitor-api";

export const MONITOR_POLL_MS = 5_000;

/** FR-15 / AC-15 / NFR-08 — 5 s poll for live roster + security alerts */
export function useSessionMonitorPoll(
  sessionId: string | undefined,
  enabled = true,
) {
  const polling = Boolean(sessionId) && enabled;

  return useQuery({
    queryKey: ["session-monitor", sessionId],
    queryFn: () => fetchSessionMonitor(sessionId!),
    enabled: polling,
    refetchInterval: polling ? MONITOR_POLL_MS : false,
    retry: false,
  });
}
