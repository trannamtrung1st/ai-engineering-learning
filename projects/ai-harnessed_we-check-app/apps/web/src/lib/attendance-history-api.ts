import type { AttendanceStatus } from "@wecheck/domain";
import { apiFetch, type ApiErrorBody } from "@/lib/api-client";

export const HISTORY_PAGE_SIZE = 20;

export interface AttendanceHistoryItem {
  sessionId: string;
  sessionDate: string;
  subject: {
    id: string;
    code: string;
    name: string;
  };
  status: AttendanceStatus;
  checkedInAt: string | null;
}

export interface AttendanceHistoryResponse {
  items: AttendanceHistoryItem[];
  nextCursor: string | null;
  totalCount: number;
}

export type AttendanceHistoryFetchResult =
  | { ok: true; data: AttendanceHistoryResponse }
  | { ok: false; status: number; error: ApiErrorBody };

export async function fetchAttendanceHistory(params: {
  cursor?: string;
  limit?: number;
}): Promise<AttendanceHistoryFetchResult> {
  const search = new URLSearchParams();
  search.set("limit", String(params.limit ?? HISTORY_PAGE_SIZE));
  if (params.cursor) {
    search.set("cursor", params.cursor);
  }

  const res = await apiFetch<AttendanceHistoryResponse>(
    `/attendance/me/history?${search.toString()}`,
  );

  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}
