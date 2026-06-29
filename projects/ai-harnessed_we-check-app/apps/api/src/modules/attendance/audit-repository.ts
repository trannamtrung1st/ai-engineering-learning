import { randomUUID } from "node:crypto";
import type { AttendanceStatus } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";

type QueryClient = { query: DbPool["query"] };

export class AuditRepository {
  constructor(private readonly db: DbPool) {}

  async insertManualEdit(
    client: QueryClient,
    input: {
      attendanceRecordId: string;
      editorId: string;
      previousStatus: AttendanceStatus;
      newStatus: AttendanceStatus;
      note: string | null;
      editedAt: Date;
    },
  ): Promise<void> {
    await client.query(
      `INSERT INTO attendance_audit_logs
         (id, attendance_record_id, editor_id, previous_status, new_status, note, edited_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7)`,
      [
        randomUUID(),
        input.attendanceRecordId,
        input.editorId,
        input.previousStatus,
        input.newStatus,
        input.note,
        input.editedAt,
      ],
    );
  }

  async countForRecord(attendanceRecordId: string): Promise<number> {
    const result = await this.db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count
       FROM attendance_audit_logs
       WHERE attendance_record_id = $1`,
      [attendanceRecordId],
    );
    return Number.parseInt(result.rows[0]?.count ?? "0", 10);
  }

  async listForRecord(attendanceRecordId: string): Promise<
    Array<{
      id: string;
      editorId: string;
      editorDisplayName: string;
      previousStatus: AttendanceStatus;
      newStatus: AttendanceStatus;
      note: string | null;
      editedAt: Date;
    }>
  > {
    const result = await this.db.query<{
      id: string;
      editor_id: string;
      editor_display_name: string;
      previous_status: AttendanceStatus;
      new_status: AttendanceStatus;
      note: string | null;
      edited_at: Date;
    }>(
      `SELECT a.id, a.editor_id, u.display_name AS editor_display_name,
              a.previous_status, a.new_status, a.note, a.edited_at
       FROM attendance_audit_logs a
       JOIN users u ON u.id = a.editor_id
       WHERE a.attendance_record_id = $1
       ORDER BY a.edited_at DESC`,
      [attendanceRecordId],
    );
    return result.rows.map((row) => ({
      id: row.id,
      editorId: row.editor_id,
      editorDisplayName: row.editor_display_name,
      previousStatus: row.previous_status,
      newStatus: row.new_status,
      note: row.note,
      editedAt: row.edited_at,
    }));
  }

  async findLatestForRecord(attendanceRecordId: string): Promise<{
    editorId: string;
    previousStatus: AttendanceStatus;
    newStatus: AttendanceStatus;
    note: string | null;
    editedAt: Date;
  } | null> {
    const result = await this.db.query<{
      editor_id: string;
      previous_status: AttendanceStatus;
      new_status: AttendanceStatus;
      note: string | null;
      edited_at: Date;
    }>(
      `SELECT editor_id, previous_status, new_status, note, edited_at
       FROM attendance_audit_logs
       WHERE attendance_record_id = $1
       ORDER BY edited_at DESC
       LIMIT 1`,
      [attendanceRecordId],
    );
    const row = result.rows[0];
    if (!row) {
      return null;
    }
    return {
      editorId: row.editor_id,
      previousStatus: row.previous_status,
      newStatus: row.new_status,
      note: row.note,
      editedAt: row.edited_at,
    };
  }
}
