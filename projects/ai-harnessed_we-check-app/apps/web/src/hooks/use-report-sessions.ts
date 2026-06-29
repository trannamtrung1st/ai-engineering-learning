import { useQuery } from "@tanstack/react-query";
import {
  fetchSessionSummaries,
  type ReportFilterParams,
} from "@/lib/reports-api";

/** FR-12 / AC-12 — closed session summaries for report tables */
export function useReportSessions(filters: ReportFilterParams | null) {
  return useQuery({
    queryKey: ["reports", "sessions", filters],
    queryFn: async () => {
      if (!filters) {
        throw new Error("ReportFilterRequired");
      }
      const result = await fetchSessionSummaries(filters);
      if (!result.ok) {
        const err = new Error(result.error.errorCode ?? "ReportFetchFailed") as Error & {
          status?: number;
          errorBody?: typeof result.error;
        };
        err.status = result.status;
        err.errorBody = result.error;
        throw err;
      }
      return result.data;
    },
    enabled: filters !== null,
    retry: false,
  });
}
