import type { ReportFilterParams } from "@/lib/reports-api";
import { defaultReportDateRange } from "@/lib/report-date-defaults";

/** Parse deep-link report filters from /reports?classCode=&subjectCode= (AC-12, BR-08). */
export function parseReportFiltersFromSearchParams(
  params: URLSearchParams,
): ReportFilterParams | null {
  const classCode = params.get("classCode")?.trim() ?? "";
  const subjectCode = params.get("subjectCode")?.trim() ?? "";
  if (!classCode || !subjectCode) return null;

  const defaults = defaultReportDateRange();
  const from = params.get("from")?.trim() || defaults.from;
  const to = params.get("to")?.trim() || defaults.to;

  return { classCode, subjectCode, from, to };
}
