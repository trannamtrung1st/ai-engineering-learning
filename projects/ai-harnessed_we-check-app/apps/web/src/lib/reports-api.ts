import type { AttendanceStatus } from "@wecheck/domain";
import { apiFetch, type ApiErrorBody } from "@/lib/api-client";

export interface ReportFilterParams {
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

export type ReportFetchResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; error: ApiErrorBody };

function buildSummaryQuery(filters: ReportFilterParams): string {
  const params = new URLSearchParams({
    classCode: filters.classCode,
    subjectCode: filters.subjectCode,
    from: filters.from,
    to: filters.to,
  });
  return `/reports/summary?${params.toString()}`;
}

export async function fetchClassSubjectSummary(
  filters: ReportFilterParams,
): Promise<ReportFetchResult<ClassSubjectSummaryDto>> {
  const res = await apiFetch<ClassSubjectSummaryDto>(buildSummaryQuery(filters));
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
