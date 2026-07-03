import { ATTENDANCE_STATUSES } from "../attendance-ledger/types.js";
import { isUuid } from "../academic-structure/validation.js";
import { REPORT_SORT_FIELDS, type AttendanceReportFilters, type ReportSortField } from "./types.js";

export type ReportValidationError =
  | { code: "InvalidFilter"; details?: Record<string, unknown> }
  | { code: "InvalidPayload"; details?: Record<string, unknown> }
  | { code: "UnsupportedFormat"; details?: Record<string, unknown> };

const ALLOWED_QUERY_KEYS = new Set([
  "termId",
  "classSectionId",
  "studentUserId",
  "status",
  "from",
  "to",
  "courseId",
  "lecturerUserId",
  "search",
  "sortBy",
  "sortOrder",
  "page",
  "pageSize",
]);

export function parseReportQuery(raw: Record<string, unknown>): {
  filters: AttendanceReportFilters;
  sortBy: ReportSortField;
  sortOrder: "asc" | "desc";
  page: number;
  pageSize: number;
  error: ReportValidationError | null;
} {
  for (const key of Object.keys(raw)) {
    if (!ALLOWED_QUERY_KEYS.has(key)) {
      return {
        filters: {},
        sortBy: "date",
        sortOrder: "desc",
        page: 1,
        pageSize: 25,
        error: { code: "InvalidFilter", details: { field: key } },
      };
    }
  }

  const pageRaw = raw.page;
  const pageSizeRaw = raw.pageSize;
  const page = pageRaw === undefined ? 1 : Number.parseInt(String(pageRaw), 10);
  const pageSizeParsed =
    pageSizeRaw === undefined ? 25 : Number.parseInt(String(pageSizeRaw), 10);

  if (!Number.isFinite(page) || page < 1) {
    return {
      filters: {},
      sortBy: "date",
      sortOrder: "desc",
      page: 1,
      pageSize: 25,
      error: { code: "InvalidPayload", details: { field: "page" } },
    };
  }

  if (!Number.isFinite(pageSizeParsed) || pageSizeParsed < 1 || pageSizeParsed > 100) {
    return {
      filters: {},
      sortBy: "date",
      sortOrder: "desc",
      page: 1,
      pageSize: 25,
      error: { code: "InvalidPayload", details: { field: "pageSize" } },
    };
  }

  const sortByRaw = raw.sortBy === undefined ? "date" : String(raw.sortBy);
  if (!REPORT_SORT_FIELDS.includes(sortByRaw as ReportSortField)) {
    return {
      filters: {},
      sortBy: "date",
      sortOrder: "desc",
      page: 1,
      pageSize: 25,
      error: { code: "InvalidFilter", details: { field: "sortBy" } },
    };
  }

  const sortOrderRaw = raw.sortOrder === undefined ? "desc" : String(raw.sortOrder);
  if (sortOrderRaw !== "asc" && sortOrderRaw !== "desc") {
    return {
      filters: {},
      sortBy: "date",
      sortOrder: "desc",
      page: 1,
      pageSize: 25,
      error: { code: "InvalidFilter", details: { field: "sortOrder" } },
    };
  }

  const filters: AttendanceReportFilters = {};
  const uuidFields: (keyof AttendanceReportFilters)[] = [
    "termId",
    "classSectionId",
    "studentUserId",
    "courseId",
    "lecturerUserId",
  ];

  for (const field of uuidFields) {
    const value = raw[field];
    if (value === undefined || value === "") continue;
    const str = String(value);
    if (!isUuid(str)) {
      return {
        filters: {},
        sortBy: "date",
        sortOrder: "desc",
        page: 1,
        pageSize: 25,
        error: { code: "InvalidFilter", details: { field } },
      };
    }
    filters[field] = str;
  }

  if (raw.status !== undefined && raw.status !== "") {
    const status = String(raw.status);
    if (!ATTENDANCE_STATUSES.includes(status as (typeof ATTENDANCE_STATUSES)[number])) {
      return {
        filters: {},
        sortBy: "date",
        sortOrder: "desc",
        page: 1,
        pageSize: 25,
        error: { code: "InvalidFilter", details: { field: "status" } },
      };
    }
    filters.status = status;
  }

  for (const field of ["from", "to"] as const) {
    const value = raw[field];
    if (value === undefined || value === "") continue;
    const str = String(value);
    if (Number.isNaN(Date.parse(str))) {
      return {
        filters: {},
        sortBy: "date",
        sortOrder: "desc",
        page: 1,
        pageSize: 25,
        error: { code: "InvalidFilter", details: { field } },
      };
    }
    filters[field] = str;
  }

  if (raw.search !== undefined && raw.search !== "") {
    filters.search = String(raw.search).trim();
  }

  return {
    filters,
    sortBy: sortByRaw as ReportSortField,
    sortOrder: sortOrderRaw,
    page,
    pageSize: pageSizeParsed,
    error: null,
  };
}

export function validateExportBody(body: Record<string, unknown>): {
  format: "csv";
  filters: AttendanceReportFilters;
  error: ReportValidationError | null;
} {
  const format = body.format === undefined ? "" : String(body.format);
  if (format !== "csv") {
    return {
      format: "csv",
      filters: {},
      error: {
        code: "UnsupportedFormat",
        details: { allowedFormats: ["csv"] },
      },
    };
  }

  const filtersRaw =
    body.filters && typeof body.filters === "object" && !Array.isArray(body.filters)
      ? (body.filters as Record<string, unknown>)
      : {};

  const parsed = parseReportQuery({
    ...filtersRaw,
    page: "1",
    pageSize: "25",
  });

  if (parsed.error) {
    return { format: "csv", filters: {}, error: parsed.error };
  }

  return { format: "csv", filters: parsed.filters, error: null };
}
