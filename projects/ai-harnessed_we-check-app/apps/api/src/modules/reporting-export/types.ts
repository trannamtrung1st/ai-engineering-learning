import type { AttendanceStatus } from "@wecheck/domain";

export interface ReportFilter {
  classCode?: string;
  subjectCode?: string;
  from: string;
  to: string;
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

export interface CsvExportRow {
  institutionalId: string;
  displayName: string;
  classCode: string;
  subjectCode: string;
  sessionDate: string;
  attendanceStatus: AttendanceStatus;
  checkedInAt: string | null;
}

export interface ExportResult {
  csv: string;
  rowCount: number;
}
