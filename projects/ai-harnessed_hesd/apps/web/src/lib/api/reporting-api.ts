import type { ApiEnvelope } from "@attendly/domain";
import type { AttendanceHistoryRow, PaginationMeta } from "./attendance-history-api.js";
import { getAccessToken } from "../auth/session.js";
import type { ListingQueryState } from "../listing/query-state.js";
import { apiRequest } from "./client.js";
import { apiV1BaseUrl } from "./config.js";

export type AttendanceReportRow = AttendanceHistoryRow;

export type AttendanceReportResult =
  | {
      ok: true;
      rows: AttendanceReportRow[];
      pagination: PaginationMeta;
    }
  | {
      ok: false;
      code: string;
      message: string;
    };

export interface ExportJobSummary {
  exportJobId: string;
  status: "Queued" | "Processing" | "Completed" | "Failed";
  format: "csv";
}

export type ExportResult =
  | { ok: true; job: ExportJobSummary }
  | { ok: false; code: string; message: string };

export type DownloadResult =
  | { ok: true; csv: string; filename: string }
  | { ok: false; code: string; message: string };

function buildReportParams(state: ListingQueryState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.termId) params.set("termId", state.termId);
  if (state.classSectionId) params.set("classSectionId", state.classSectionId);
  if (state.search) params.set("search", state.search);
  if (state.status) params.set("status", state.status);
  if (state.from) params.set("from", state.from);
  if (state.to) params.set("to", state.to);
  params.set("sortBy", state.sortBy);
  params.set("sortOrder", state.sortOrder);
  params.set("page", String(state.page));
  params.set("pageSize", String(state.pageSize));
  return params;
}

export function buildExportFilters(state: ListingQueryState): Record<string, string> {
  const filters: Record<string, string> = {};
  if (state.termId) filters.termId = state.termId;
  if (state.classSectionId) filters.classSectionId = state.classSectionId;
  if (state.search) filters.search = state.search;
  if (state.status) filters.status = state.status;
  if (state.from) filters.from = state.from;
  if (state.to) filters.to = state.to;
  return filters;
}

export async function fetchAttendanceReport(
  query: ListingQueryState,
): Promise<AttendanceReportResult> {
  const envelope = await apiRequest<AttendanceReportRow[]>(
    `/reports/attendance?${buildReportParams(query).toString()}`,
  );

  if (envelope.data && !envelope.error) {
    const meta = envelope.meta as ApiEnvelope<AttendanceReportRow[]>["meta"] & {
      pagination?: PaginationMeta;
    };
    if (!meta.pagination) {
      return {
        ok: false,
        code: "InvalidResponse",
        message: "Thiếu thông tin phân trang báo cáo.",
      };
    }
    return { ok: true, rows: envelope.data, pagination: meta.pagination };
  }

  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải báo cáo điểm danh.",
  };
}

export async function createAttendanceExport(query: ListingQueryState): Promise<ExportResult> {
  const envelope = await apiRequest<ExportJobSummary>("/exports/attendance", {
    method: "POST",
    body: { format: "csv", filters: buildExportFilters(query) },
    idempotencyKey: crypto.randomUUID(),
  });

  if (envelope.data && !envelope.error) {
    return { ok: true, job: envelope.data };
  }

  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tạo tác vụ xuất CSV.",
  };
}

export async function downloadAttendanceExport(exportJobId: string): Promise<DownloadResult> {
  const headers: Record<string, string> = { Accept: "text/csv" };
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${apiV1BaseUrl()}/exports/attendance/${exportJobId}`, {
    method: "GET",
    headers,
  });

  if (!response.ok) {
    let message = "Không thể tải CSV đã xuất.";
    let code = "RequestFailed";
    try {
      const envelope = (await response.json()) as ApiEnvelope<null>;
      message = envelope.error?.message ?? message;
      code = envelope.error?.code ?? code;
    } catch {
      // CSV endpoint may fail before emitting JSON; keep a user-safe generic message.
    }
    return { ok: false, code, message };
  }

  const csv = await response.text();
  const disposition = response.headers.get("content-disposition") ?? "";
  const filenameMatch = /filename="([^"]+)"/.exec(disposition);
  return {
    ok: true,
    csv,
    filename: filenameMatch?.[1] ?? `attendance-export-${exportJobId}.csv`,
  };
}
