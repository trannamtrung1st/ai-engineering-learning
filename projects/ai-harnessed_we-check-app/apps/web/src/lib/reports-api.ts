import type { AttendanceStatus } from "@wecheck/domain";
import { apiFetch, type ApiErrorBody } from "@/lib/api-client";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export interface ReportFilterParams {
  classCode?: string;
  subjectCode?: string;
  from: string;
  to: string;
}

export interface ExportFilterParams {
  classCode: string;
  subjectCode: string;
  from: string;
  to: string;
}

export interface StudentSummaryRow {
  institutionalId: string;
  displayName: string;
  presentCount: number;
  absentCount: number;
  excusedCount: number;
  attendanceRate: number;
}

export interface ClassSubjectSummaryDto {
  classCode: string | null;
  subjectCode: string | null;
  dateFrom: string;
  dateTo: string;
  sessionsHeld: number;
  students: StudentSummaryRow[];
}

export interface SessionReportSummary {
  enrolled: number;
  present: number;
  absent: number;
  excused: number;
  rejected: number;
  pending: number;
}

export interface SessionReportRecord {
  institutionalId: string;
  displayName: string;
  status: AttendanceStatus;
  checkedInAt: string | null;
}

export interface SessionReportDto {
  sessionId: string;
  classCode: string;
  subjectCode: string;
  scheduledStart: string;
  closedAt: string | null;
  summary: SessionReportSummary;
  records: SessionReportRecord[];
}

export interface SessionSummaryRow {
  sessionId: string;
  scheduledStart: string;
  classCode: string;
  subjectCode: string;
  enrolled: number;
  present: number;
  absent: number;
  excused: number;
}

export interface SessionSummaryListDto {
  items: SessionSummaryRow[];
}

export type ReportFetchResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; error: ApiErrorBody };

function buildFilterQuery(filters: ReportFilterParams): string {
  const params = new URLSearchParams({
    from: filters.from,
    to: filters.to,
  });
  if (filters.classCode) {
    params.set("classCode", filters.classCode);
  }
  if (filters.subjectCode) {
    params.set("subjectCode", filters.subjectCode);
  }
  return params.toString();
}

export async function fetchClassSubjectSummary(
  filters: ReportFilterParams,
): Promise<ReportFetchResult<ClassSubjectSummaryDto>> {
  const res = await apiFetch<ClassSubjectSummaryDto>(
    `/reports/summary?${buildFilterQuery(filters)}`,
  );
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}

export async function fetchSessionSummaries(
  filters: ReportFilterParams,
): Promise<ReportFetchResult<SessionSummaryListDto>> {
  const res = await apiFetch<SessionSummaryListDto>(
    `/reports/sessions?${buildFilterQuery(filters)}`,
  );
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}

export async function fetchSessionReport(
  sessionId: string,
): Promise<ReportFetchResult<SessionReportDto>> {
  const res = await apiFetch<SessionReportDto>(`/reports/session/${sessionId}`);
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}

export async function estimateExportRowCount(
  filters: ExportFilterParams,
): Promise<ReportFetchResult<number>> {
  const params = new URLSearchParams({
    classCode: filters.classCode,
    subjectCode: filters.subjectCode,
    from: filters.from,
    to: filters.to,
  });
  const res = await fetch(`${API_BASE}/reports/export?${params.toString()}`, {
    method: "HEAD",
    credentials: "include",
  });

  if (!res.ok) {
    let error: ApiErrorBody = {};
    try {
      error = (await res.json()) as ApiErrorBody;
    } catch {
      error = { errorCode: "ExportEstimateFailed" };
    }
    return { ok: false, status: res.status, error };
  }

  const countHeader = res.headers.get("X-Export-Row-Count");
  const rowCount = countHeader ? Number.parseInt(countHeader, 10) : 0;
  return { ok: true, data: Number.isNaN(rowCount) ? 0 : rowCount };
}

export async function exportAttendanceCsv(
  filters: ExportFilterParams,
): Promise<ReportFetchResult<{ blob: Blob; filename: string }>> {
  const res = await fetch(`${API_BASE}/reports/export`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(filters),
  });

  if (!res.ok) {
    let error: ApiErrorBody = {};
    try {
      error = (await res.json()) as ApiErrorBody;
    } catch {
      error = { errorCode: "ExportFailed" };
    }
    return { ok: false, status: res.status, error };
  }

  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  const filename = match?.[1] ?? `attendance-export-${filters.to}.csv`;
  return { ok: true, data: { blob, filename } };
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
