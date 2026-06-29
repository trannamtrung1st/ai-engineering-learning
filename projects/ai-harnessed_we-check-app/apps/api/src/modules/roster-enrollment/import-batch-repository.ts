import { randomUUID } from "node:crypto";
import { RosterImportStatus, type RosterImportStatus as RosterImportStatusType } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import type { ImportErrorDetail } from "./types.js";

interface BatchRow {
  id: string;
  uploaded_by_id: string;
  file_name: string;
  status: RosterImportStatusType;
  total_rows: number;
  success_rows: number;
  error_rows: number;
  error_details: ImportErrorDetail[] | null;
  started_at: Date;
  completed_at: Date | null;
}

export interface ImportBatchRecord {
  batchId: string;
  uploadedById: string;
  fileName: string;
  status: RosterImportStatusType;
  totalRows: number;
  successRows: number;
  errorRows: number;
  errorDetails: ImportErrorDetail[];
  startedAt: Date;
  completedAt: Date | null;
}

function mapBatch(row: BatchRow): ImportBatchRecord {
  return {
    batchId: row.id,
    uploadedById: row.uploaded_by_id,
    fileName: row.file_name,
    status: row.status,
    totalRows: row.total_rows,
    successRows: row.success_rows,
    errorRows: row.error_rows,
    errorDetails: row.error_details ?? [],
    startedAt: row.started_at,
    completedAt: row.completed_at,
  };
}

export class ImportBatchRepository {
  constructor(private readonly db: DbPool) {}

  async createProcessing(
    uploadedById: string,
    fileName: string,
  ): Promise<string> {
    const id = randomUUID();
    await this.db.query(
      `INSERT INTO roster_import_batches (id, uploaded_by_id, file_name, status)
       VALUES ($1, $2, $3, $4)`,
      [id, uploadedById, fileName, RosterImportStatus.Processing],
    );
    return id;
  }

  async complete(
    batchId: string,
    summary: {
      totalRows: number;
      successRows: number;
      errorRows: number;
      errorDetails: ImportErrorDetail[];
    },
  ): Promise<void> {
    await this.db.query(
      `UPDATE roster_import_batches
       SET status = $2,
           total_rows = $3,
           success_rows = $4,
           error_rows = $5,
           error_details = $6,
           completed_at = NOW()
       WHERE id = $1`,
      [
        batchId,
        RosterImportStatus.Completed,
        summary.totalRows,
        summary.successRows,
        summary.errorRows,
        JSON.stringify(summary.errorDetails),
      ],
    );
  }

  async findById(batchId: string): Promise<ImportBatchRecord | null> {
    const result = await this.db.query<BatchRow>(
      `SELECT id, uploaded_by_id, file_name, status, total_rows, success_rows,
              error_rows, error_details, started_at, completed_at
       FROM roster_import_batches WHERE id = $1`,
      [batchId],
    );
    const row = result.rows[0];
    return row ? mapBatch(row) : null;
  }
}
