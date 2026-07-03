export const REPORT_SORT_FIELDS = ["date", "status", "classSectionId"] as const;
export type ReportSortField = (typeof REPORT_SORT_FIELDS)[number];

export const EXPORT_FORMATS = ["csv"] as const;
export type ExportFormat = (typeof EXPORT_FORMATS)[number];

export const EXPORT_JOB_STATUSES = ["Queued", "Processing", "Completed", "Failed"] as const;
export type ExportJobStatus = (typeof EXPORT_JOB_STATUSES)[number];

export interface AttendanceReportFilters {
  termId?: string;
  classSectionId?: string;
  studentUserId?: string;
  status?: string;
  from?: string;
  to?: string;
  courseId?: string;
  lecturerUserId?: string;
  search?: string;
}

export interface AttendanceReportRow {
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

export interface ExportJobResult {
  exportJobId: string;
  status: ExportJobStatus;
  format: ExportFormat;
  rowCount?: number;
}

export interface ResolvedReportScope {
  classSectionIds: string[] | null;
  /** FR-37: mandatory self-filter for student personal history */
  studentUserId?: string;
}
