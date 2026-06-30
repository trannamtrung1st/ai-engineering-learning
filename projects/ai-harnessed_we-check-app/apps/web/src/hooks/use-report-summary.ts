import { useQuery } from "@tanstack/react-query";
import {
  fetchClassSubjectSummary,
  type ReportFilterParams,
} from "@/lib/reports-api";

/** FR-12 / AC-12 / BR-08 — instructor class-subject summary report */
export function useReportSummary(filters: ReportFilterParams | null) {
  return useQuery({
    queryKey: ["reports", "summary", filters],
    queryFn: async () => {
      if (!filters) {
        throw new Error("ReportFilterRequired");
      }
      const result = await fetchClassSubjectSummary(filters);
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
