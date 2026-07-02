import { randomUUID } from "node:crypto";
import { UserImportStatus, type UserImportStatus as UserImportStatusType } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import type { UserImportErrorDetail } from "./user-import-types.js";

interface BatchRow {
  id: string;
  uploaded_by_id: string;
  file_name: string;
  status: UserImportStatusType;
  total_rows: number;
  success_rows: number;
  error_rows: number;
  created_count: number;
  updated_count: number;
  error_details: UserImportErrorDetail[] | null;
  started_at: Date;
  completed_at: Date | null;
}

export interface UserImportBatchRecord {
  batchId: string;
  uploadedById: string;
  fileName: string;
  status: UserImportStatusType;
  totalRows: number;
  successRows: number;
  errorRows: number;
  createdCount: number;
  updatedCount: number;
  errorDetails: UserImportErrorDetail[];
  startedAt: Date;
  completedAt: Date | null;
}

function mapBatch(row: BatchRow): UserImportBatchRecord {
  return {
    batchId: row.id,
    uploadedById: row.uploaded_by_id,
    fileName: row.file_name,
    status: row.status,
    totalRows: row.total_rows,
    successRows: row.success_rows,
    errorRows: row.error_rows,
    createdCount: row.created_count,
    updatedCount: row.updated_count,
    errorDetails: row.error_details ?? [],
    startedAt: row.started_at,
    completedAt: row.completed_at,
  };
}

export class UserImportBatchRepository {
  constructor(private readonly db: DbPool) {}

  async createProcessing(
    uploadedById: string,
    fileName: string,
  ): Promise<string> {
    const id = randomUUID();
    await this.db.query(
      `INSERT INTO user_import_batches (id, uploaded_by_id, file_name, status)
       VALUES ($1, $2, $3, $4)`,
      [id, uploadedById, fileName, UserImportStatus.Processing],
    );
    return id;
  }

  async complete(
    batchId: string,
    summary: {
      totalRows: number;
      successRows: number;
      errorRows: number;
      createdCount: number;
      updatedCount: number;
      errorDetails: UserImportErrorDetail[];
    },
  ): Promise<void> {
    await this.db.query(
      `UPDATE user_import_batches
       SET status = $2,
           total_rows = $3,
           success_rows = $4,
           error_rows = $5,
           created_count = $6,
           updated_count = $7,
           error_details = $8,
           completed_at = NOW()
       WHERE id = $1`,
      [
        batchId,
        UserImportStatus.Completed,
        summary.totalRows,
        summary.successRows,
        summary.errorRows,
        summary.createdCount,
        summary.updatedCount,
        JSON.stringify(summary.errorDetails),
      ],
    );
  }

  async findById(batchId: string): Promise<UserImportBatchRecord | null> {
    const result = await this.db.query<BatchRow>(
      `SELECT id, uploaded_by_id, file_name, status, total_rows, success_rows,
              error_rows, created_count, updated_count, error_details,
              started_at, completed_at
       FROM user_import_batches WHERE id = $1`,
      [batchId],
    );
    const row = result.rows[0];
    return row ? mapBatch(row) : null;
  }
}
