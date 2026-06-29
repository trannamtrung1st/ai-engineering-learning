import type { RosterImportStatus } from "@wecheck/domain";

export interface ClassRecord {
  id: string;
  code: string;
  name: string;
  term: string | null;
}

export interface SubjectRecord {
  id: string;
  code: string;
  name: string;
}

export interface EnrollmentRecord {
  enrollmentId: string;
  studentId: string;
  institutionalId: string;
  displayName: string;
  enrolledAt: Date;
}

export interface ImportErrorDetail {
  rowNumber: number;
  errorCode: string;
  message: string;
}

export interface ImportSummary {
  batchId: string;
  status: RosterImportStatus;
  totalRows: number;
  successRows: number;
  errorRows: number;
  errorDetails: ImportErrorDetail[];
}

export interface ParsedCsvRow {
  rowNumber: number;
  institutionalId: string;
  displayName: string;
  classCode: string;
  subjectCode: string;
}

export interface ImportCsvOptions {
  uploadedById: string;
  fileName: string;
  dryRun?: boolean;
}
