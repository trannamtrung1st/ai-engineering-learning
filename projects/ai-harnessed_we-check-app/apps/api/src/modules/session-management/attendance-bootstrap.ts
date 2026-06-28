import { randomUUID } from "node:crypto";
import { AttendanceStatus } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import type { AttendanceRecordDto, AttendanceSummary } from "./types.js";

export class AttendanceBootstrap {
  constructor(private readonly db: DbPool) {}

  async initializeForSession(
    client: { query: DbPool["query"] },
    sessionId: string,
    classId: string,
    subjectId: string,
  ): Promise<number> {
    const enrollments = await client.query<{ student_id: string }>(
      `SELECT student_id FROM enrollments WHERE class_id = $1 AND subject_id = $2`,
      [classId, subjectId],
    );

    for (const row of enrollments.rows) {
      await client.query(
        `INSERT INTO attendance_records (id, session_id, student_id, status)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT (session_id, student_id) DO NOTHING`,
        [randomUUID(), sessionId, row.student_id, AttendanceStatus.Pending],
      );
    }

    return enrollments.rowCount ?? 0;
  }

  async finalizeOnClose(
    client: { query: DbPool["query"] },
    sessionId: string,
  ): Promise<number> {
    const result = await client.query(
      `UPDATE attendance_records
       SET status = $2, updated_at = NOW(), version = version + 1
       WHERE session_id = $1 AND status = $3`,
      [sessionId, AttendanceStatus.Absent, AttendanceStatus.Pending],
    );
    return result.rowCount ?? 0;
  }

  async getSummary(sessionId: string): Promise<AttendanceSummary> {
    const result = await this.db.query<{
      status: string;
      count: string;
    }>(
      `SELECT status, COUNT(*)::text AS count
       FROM attendance_records
       WHERE session_id = $1
       GROUP BY status`,
      [sessionId],
    );

    const summary: AttendanceSummary = {
      enrolled: 0,
      pending: 0,
      present: 0,
      absent: 0,
      excused: 0,
      rejected: 0,
    };

    for (const row of result.rows) {
      const count = Number.parseInt(row.count, 10);
      summary.enrolled += count;
      switch (row.status) {
        case AttendanceStatus.Pending:
          summary.pending = count;
          break;
        case AttendanceStatus.Present:
          summary.present = count;
          break;
        case AttendanceStatus.Absent:
          summary.absent = count;
          break;
        case AttendanceStatus.Excused:
          summary.excused = count;
          break;
        case AttendanceStatus.Rejected:
          summary.rejected = count;
          break;
      }
    }

    return summary;
  }

  async listRecords(sessionId: string): Promise<AttendanceRecordDto[]> {
    const result = await this.db.query<{
      id: string;
      student_id: string;
      institutional_id: string;
      display_name: string;
      status: string;
      checked_in_at: Date | null;
    }>(
      `SELECT ar.id, ar.student_id, u.institutional_id, u.display_name,
              ar.status, ar.checked_in_at
       FROM attendance_records ar
       JOIN users u ON u.id = ar.student_id
       WHERE ar.session_id = $1
       ORDER BY u.display_name`,
      [sessionId],
    );

    return result.rows.map((row) => ({
      id: row.id,
      studentId: row.student_id,
      institutionalId: row.institutional_id,
      displayName: row.display_name,
      status: row.status,
      checkedInAt: row.checked_in_at?.toISOString() ?? null,
    }));
  }

  async countForSession(sessionId: string): Promise<number> {
    const result = await this.db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM attendance_records WHERE session_id = $1`,
      [sessionId],
    );
    return Number.parseInt(result.rows[0]?.count ?? "0", 10);
  }
}
