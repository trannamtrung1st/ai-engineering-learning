import type { UserRole } from "@wecheck/domain";
import type { UserImportStatus } from "@wecheck/domain";

export interface UserImportErrorDetail {
  rowNumber: number;
  field?: string;
  errorCode: string;
  message: string;
}

export interface ParsedUserCsvRow {
  rowNumber: number;
  institutionalId: string;
  displayName: string;
  email: string;
  role: UserRole;
  active: boolean;
  rawRole: string;
  rawActive: string;
}

export interface UserImportSummary {
  batchId: string;
  status: UserImportStatus;
  totalRows: number;
  successRows: number;
  errorRows: number;
  createdCount: number;
  updatedCount: number;
  errorDetails: UserImportErrorDetail[];
}

export interface UserImportCsvOptions {
  uploadedById: string;
  fileName: string;
  dryRun?: boolean;
}
