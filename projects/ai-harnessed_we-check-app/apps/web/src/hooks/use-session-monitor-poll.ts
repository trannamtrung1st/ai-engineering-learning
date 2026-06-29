import { useQuery } from "@tanstack/react-query";
import { fetchSessionMonitor } from "@/lib/session-monitor-api";

export const MONITOR_POLL_MS = 5_000;

/** FR-15 / AC-15 / NFR-08 — 5 s poll for live roster + security alerts */
export function useSessionMonitorPoll(
  sessionId: string | undefined,
  pollingEnabled = true,
) {
  const hasSession = Boolean(sessionId);

  return useQuery({
    queryKey: ["session-monitor", sessionId],
    queryFn: () => fetchSessionMonitor(sessionId!),
    // Closed sessions still load roster once (AC-05 / TC-AC-05-020); only polling stops.
    enabled: hasSession,
    refetchInterval: hasSession && pollingEnabled ? MONITOR_POLL_MS : false,
    retry: false,
  });
}
