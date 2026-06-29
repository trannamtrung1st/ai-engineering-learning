import { useQuery } from "@tanstack/react-query";
import { fetchSessionReport } from "@/lib/reports-api";

/** FR-12 / AC-12 — per-session attendance report drill-down */
export function useSessionReport(sessionId: string | undefined) {
  return useQuery({
    queryKey: ["reports", "session", sessionId],
    queryFn: async () => {
      if (!sessionId) {
        throw new Error("SessionIdRequired");
      }
      const result = await fetchSessionReport(sessionId);
      if (!result.ok) {
        const err = new Error(result.error.errorCode ?? "SessionReportFetchFailed") as Error & {
          status?: number;
          errorBody?: typeof result.error;
        };
        err.status = result.status;
        err.errorBody = result.error;
        throw err;
      }
      return result.data;
    },
    enabled: Boolean(sessionId),
    retry: false,
  });
}
