import { randomUUID } from "node:crypto";
import { AttendanceStatus } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import type {
  AttendanceRecordRow,
  AttendanceSummary,
  SessionContextRow,
  StudentHistoryItemDto,
} from "./types.js";

type QueryClient = { query: DbPool["query"] };

interface AttendanceRecordDbRow {
  id: string;
  session_id: string;
  student_id: string;
  status: AttendanceStatus;
  checked_in_at: Date | null;
  version: number;
}

interface SessionDbRow {
  id: string;
  instructor_id: string;
  class_id: string;
  subject_id: string;
  status: SessionContextRow["status"];
  closed_at: Date | null;
}

interface HistoryDbRow {
  session_id: string;
  scheduled_start: Date;
  subject_id: string;
  subject_code: string;
  subject_name: string;
  status: AttendanceStatus;
  checked_in_at: Date | null;
}

export class AttendanceRepository {
  constructor(private readonly db: DbPool) {}

  async initializeForSession(
    client: QueryClient,
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

  async finalizeOnClose(client: QueryClient, sessionId: string): Promise<number> {
    const result = await client.query(
      `UPDATE attendance_records
       SET status = $2, updated_at = NOW(), version = version + 1
       WHERE session_id = $1 AND status = $3`,
      [sessionId, AttendanceStatus.Absent, AttendanceStatus.Pending],
    );
    return result.rowCount ?? 0;
  }

  async getSummary(sessionId: string): Promise<AttendanceSummary> {
    const result = await this.db.query<{ status: string; count: string }>(
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

  async listRecords(sessionId: string): Promise<
    Array<{
      id: string;
      studentId: string;
      institutionalId: string;
      displayName: string;
      status: AttendanceStatus;
      checkedInAt: string | null;
    }>
  > {
    const result = await this.db.query<{
      id: string;
      student_id: string;
      institutional_id: string;
      display_name: string;
      status: AttendanceStatus;
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

  async findRecordById(recordId: string): Promise<
    (AttendanceRecordRow & {
      institutionalId: string;
      displayName: string;
    }) | null
  > {
    const result = await this.db.query<
      AttendanceRecordDbRow & {
        institutional_id: string;
        display_name: string;
      }
    >(
      `SELECT ar.id, ar.session_id, ar.student_id, ar.status, ar.checked_in_at, ar.version,
              u.institutional_id, u.display_name
       FROM attendance_records ar
       JOIN users u ON u.id = ar.student_id
       WHERE ar.id = $1`,
      [recordId],
    );
    const row = result.rows[0];
    if (!row) {
      return null;
    }
    return {
      id: row.id,
      sessionId: row.session_id,
      studentId: row.student_id,
      status: row.status,
      checkedInAt: row.checked_in_at,
      version: row.version,
      institutionalId: row.institutional_id,
      displayName: row.display_name,
    };
  }

  async findSessionContext(sessionId: string): Promise<SessionContextRow | null> {
    const result = await this.db.query<SessionDbRow>(
      `SELECT id, instructor_id, class_id, subject_id, status, closed_at
       FROM sessions WHERE id = $1`,
      [sessionId],
    );
    const row = result.rows[0];
    if (!row) {
      return null;
    }
    return {
      id: row.id,
      instructorId: row.instructor_id,
      classId: row.class_id,
      subjectId: row.subject_id,
      status: row.status,
      closedAt: row.closed_at,
    };
  }

  async updateStatus(
    client: QueryClient,
    recordId: string,
    status: AttendanceStatus,
    checkedInAt: Date | null,
    version: number,
  ): Promise<AttendanceRecordRow | null> {
    const result = await client.query<AttendanceRecordDbRow>(
      `UPDATE attendance_records
       SET status = $2, checked_in_at = $3, updated_at = NOW(), version = version + 1
       WHERE id = $1 AND version = $4
       RETURNING id, session_id, student_id, status, checked_in_at, version`,
      [recordId, status, checkedInAt, version],
    );
    const row = result.rows[0];
    if (!row) {
      return null;
    }
    return {
      id: row.id,
      sessionId: row.session_id,
      studentId: row.student_id,
      status: row.status,
      checkedInAt: row.checked_in_at,
      version: row.version,
    };
  }

  async countStudentHistory(
    studentId: string,
    filters: { subjectId?: string; from?: string; to?: string },
  ): Promise<number> {
    const { conditions, values } = this.buildHistoryFilters(studentId, filters);
    const result = await this.db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count
       FROM attendance_records ar
       JOIN sessions s ON s.id = ar.session_id
       WHERE ${conditions.join(" AND ")}`,
      values,
    );
    return Number.parseInt(result.rows[0]?.count ?? "0", 10);
  }

  async listStudentHistory(
    studentId: string,
    filters: {
      subjectId?: string;
      from?: string;
      to?: string;
      limit: number;
      cursor?: { scheduledStart: string; sessionId: string };
    },
  ): Promise<{ items: StudentHistoryItemDto[]; hasMore: boolean }> {
    const { conditions, values, nextIdx } = this.buildHistoryFilters(
      studentId,
      filters,
    );
    let idx = nextIdx;

    if (filters.cursor) {
      conditions.push(
        `(s.scheduled_start, s.id) < ($${idx}::timestamptz, $${idx + 1}::uuid)`,
      );
      values.push(filters.cursor.scheduledStart, filters.cursor.sessionId);
      idx += 2;
    }

    values.push(filters.limit + 1);
    const result = await this.db.query<HistoryDbRow>(
      `SELECT s.id AS session_id, s.scheduled_start,
              sub.id AS subject_id, sub.code AS subject_code, sub.name AS subject_name,
              ar.status, ar.checked_in_at
       FROM attendance_records ar
       JOIN sessions s ON s.id = ar.session_id
       JOIN subjects sub ON sub.id = s.subject_id
       WHERE ${conditions.join(" AND ")}
       ORDER BY s.scheduled_start DESC, s.id DESC
       LIMIT $${idx}`,
      values,
    );

    const hasMore = result.rows.length > filters.limit;
    const page = hasMore ? result.rows.slice(0, filters.limit) : result.rows;

    return {
      items: page.map((row) => ({
        sessionId: row.session_id,
        sessionDate: row.scheduled_start.toISOString(),
        subject: {
          id: row.subject_id,
          code: row.subject_code,
          name: row.subject_name,
        },
        status: row.status,
        checkedInAt: row.checked_in_at?.toISOString() ?? null,
      })),
      hasMore,
    };
  }

  private buildHistoryFilters(
    studentId: string,
    filters: { subjectId?: string; from?: string; to?: string },
  ): { conditions: string[]; values: unknown[]; nextIdx: number } {
    const conditions = ["ar.student_id = $1", "s.status = 'Closed'"];
    const values: unknown[] = [studentId];
    let idx = 2;

    if (filters.subjectId) {
      conditions.push(`s.subject_id = $${idx++}`);
      values.push(filters.subjectId);
    }
    if (filters.from) {
      conditions.push(`s.scheduled_start >= $${idx++}::date`);
      values.push(filters.from);
    }
    if (filters.to) {
      conditions.push(`s.scheduled_start < ($${idx++}::date + INTERVAL '1 day')`);
      values.push(filters.to);
    }

    return { conditions, values, nextIdx: idx };
  }
}
