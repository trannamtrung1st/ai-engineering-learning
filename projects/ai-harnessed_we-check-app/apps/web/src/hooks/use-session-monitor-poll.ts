import { useQuery } from "@tanstack/react-query";
import { fetchSessionMonitor } from "@/lib/session-monitor-api";

const MONITOR_POLL_MS = 5_000;

/** FR-15 / AC-10 — 5 s poll for live roster + security alerts */
export function useSessionMonitorPoll(sessionId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["session-monitor", sessionId],
    queryFn: () => fetchSessionMonitor(sessionId!),
    enabled: Boolean(sessionId) && enabled,
    refetchInterval: MONITOR_POLL_MS,
    retry: false,
  });
}
