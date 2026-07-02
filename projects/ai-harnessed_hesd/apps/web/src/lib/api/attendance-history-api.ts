import type { ApiEnvelope } from "@attendly/domain";
import type { ListingQueryState } from "../listing/query-state.js";
import { apiRequest } from "./client.js";

export interface AttendanceHistoryRow {
  attendanceRecordId: string;
  studentUserId: string;
  studentCode: string;
  classSessionId: string;
  classSectionId: string;
  sectionCode: string;
  attendanceStatus: string;
  checkInAt: string | null;
  checkInMethod: string | null;
  sessionDate: string;
}

export interface PaginationMeta {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
}

export type AttendanceHistoryResult =
  | {
      ok: true;
      rows: AttendanceHistoryRow[];
      pagination: PaginationMeta;
    }
  | {
      ok: false;
      code: string;
      message: string;
    };

function buildReportQuery(state: ListingQueryState): string {
  const params = new URLSearchParams();
  if (state.termId) params.set("termId", state.termId);
  if (state.classSectionId) params.set("classSectionId", state.classSectionId);
  if (state.status) params.set("status", state.status);
  params.set("sortBy", state.sortBy);
  params.set("sortOrder", state.sortOrder);
  params.set("page", String(state.page));
  params.set("pageSize", String(state.pageSize));
  return `/reports/attendance?${params.toString()}`;
}

export async function fetchAttendanceHistory(
  query: ListingQueryState,
): Promise<AttendanceHistoryResult> {
  const envelope = await apiRequest<AttendanceHistoryRow[]>(buildReportQuery(query));

  if (envelope.data && !envelope.error) {
    const meta = envelope.meta as ApiEnvelope<AttendanceHistoryRow[]>["meta"] & {
      pagination?: PaginationMeta;
    };
    const pagination = meta.pagination;
    if (!pagination) {
      return {
        ok: false,
        code: "InvalidResponse",
        message: "Thiếu thông tin phân trang.",
      };
    }
    return {
      ok: true,
      rows: envelope.data,
      pagination: pagination as PaginationMeta,
    };
  }

  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải lịch sử điểm danh.",
  };
}

export function groupRowsBySection(
  rows: AttendanceHistoryRow[],
): Map<string, AttendanceHistoryRow[]> {
  const groups = new Map<string, AttendanceHistoryRow[]>();
  for (const row of rows) {
    const key = row.sectionCode || row.classSectionId;
    const bucket = groups.get(key) ?? [];
    bucket.push(row);
    groups.set(key, bucket);
  }
  return groups;
}
