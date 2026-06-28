import { randomUUID } from "node:crypto";
import {
  AttendanceStatus,
  SessionStatus,
  type AttendanceStatus as AttendanceStatusType,
} from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import type {
  ClassSubjectSummaryDto,
  CsvExportRow,
  ReportFilter,
  SessionReportDto,
  SessionReportRecord,
  SessionReportSummary,
  StudentSummaryRow,
} from "./types.js";

interface SessionContextRow {
  id: string;
  class_id: string;
  subject_id: string;
  class_code: string;
  subject_code: string;
  scheduled_start: Date;
  closed_at: Date | null;
  status: string;
}

interface AttendanceRow {
  institutional_id: string;
  display_name: string;
  status: AttendanceStatusType;
  checked_in_at: Date | null;
}

interface SummaryAggRow {
  institutional_id: string;
  display_name: string;
  present_count: string;
  absent_count: string;
  excused_count: string;
}

interface CsvRow {
  institutional_id: string;
  display_name: string;
  class_code: string;
  subject_code: string;
  session_date: Date;
  status: AttendanceStatusType;
  checked_in_at: Date | null;
}

function countStatus(
  records: readonly { status: AttendanceStatusType }[],
): SessionReportSummary {
  const summary: SessionReportSummary = {
    enrolled: records.length,
    present: 0,
    absent: 0,
    excused: 0,
    rejected: 0,
    pending: 0,
  };
  for (const record of records) {
    switch (record.status) {
      case AttendanceStatus.Present:
        summary.present += 1;
        break;
      case AttendanceStatus.Absent:
        summary.absent += 1;
        break;
      case AttendanceStatus.Excused:
        summary.excused += 1;
        break;
      case AttendanceStatus.Rejected:
        summary.rejected += 1;
        break;
      case AttendanceStatus.Pending:
        summary.pending += 1;
        break;
      default:
        break;
    }
  }
  return summary;
}

function toSessionRecords(rows: AttendanceRow[]): SessionReportRecord[] {
  return rows.map((row) => ({
    institutionalId: row.institutional_id,
    displayName: row.display_name,
    status: row.status,
    checkedInAt: row.checked_in_at?.toISOString() ?? null,
  }));
}

function computeRate(presentCount: number, sessionsHeld: number): number {
  if (sessionsHeld <= 0) {
    return 0;
  }
  return Math.round((presentCount / sessionsHeld) * 1000) / 1000;
}

export class ReportRepository {
  constructor(private readonly db: DbPool) {}

  async findSessionContext(sessionId: string): Promise<SessionContextRow | null> {
    const result = await this.db.query<SessionContextRow>(
      `SELECT s.id, s.class_id, s.subject_id, s.scheduled_start, s.closed_at, s.status,
              c.code AS class_code, sub.code AS subject_code
       FROM sessions s
       INNER JOIN classes c ON c.id = s.class_id
       INNER JOIN subjects sub ON sub.id = s.subject_id
       WHERE s.id = $1`,
      [sessionId],
    );
    return result.rows[0] ?? null;
  }

  async listSessionAttendance(sessionId: string): Promise<AttendanceRow[]> {
    const result = await this.db.query<AttendanceRow>(
      `SELECT u.institutional_id, u.display_name, ar.status, ar.checked_in_at
       FROM attendance_records ar
       INNER JOIN users u ON u.id = ar.student_id
       WHERE ar.session_id = $1
       ORDER BY u.display_name`,
      [sessionId],
    );
    return result.rows;
  }

  async getSessionReport(sessionId: string): Promise<SessionReportDto | null> {
    const session = await this.findSessionContext(sessionId);
    if (!session) {
      return null;
    }

    const rows = await this.listSessionAttendance(sessionId);
    const records = toSessionRecords(rows);

    return {
      sessionId: session.id,
      classCode: session.class_code,
      subjectCode: session.subject_code,
      scheduledStart: session.scheduled_start.toISOString(),
      closedAt: session.closed_at?.toISOString() ?? null,
      summary: countStatus(records),
      records,
    };
  }

  async countClosedSessions(
    filters: ReportFilter,
    classId?: string,
    subjectId?: string,
  ): Promise<number> {
    const params: unknown[] = [filters.from, filters.to, SessionStatus.Closed];
    let sql = `
      SELECT COUNT(*)::int AS count
      FROM sessions s
      INNER JOIN classes c ON c.id = s.class_id
      INNER JOIN subjects sub ON sub.id = s.subject_id
      WHERE s.status = $3
        AND DATE(s.scheduled_start AT TIME ZONE 'UTC') >= $1::date
        AND DATE(s.scheduled_start AT TIME ZONE 'UTC') <= $2::date`;

    if (classId) {
      params.push(classId);
      sql += ` AND s.class_id = $${params.length}`;
    }
    if (subjectId) {
      params.push(subjectId);
      sql += ` AND s.subject_id = $${params.length}`;
    }

    const result = await this.db.query<{ count: number }>(sql, params);
    return result.rows[0]?.count ?? 0;
  }

  async aggregateStudentSummary(
    filters: ReportFilter,
    classId?: string,
    subjectId?: string,
  ): Promise<StudentSummaryRow[]> {
    const params: unknown[] = [filters.from, filters.to, SessionStatus.Closed];
    let enrollmentJoin = "";
    const sessionJoin = `
      LEFT JOIN sessions s ON s.class_id = e.class_id
        AND s.subject_id = e.subject_id
        AND s.status = $3
        AND DATE(s.scheduled_start AT TIME ZONE 'UTC') >= $1::date
        AND DATE(s.scheduled_start AT TIME ZONE 'UTC') <= $2::date`;

    if (classId) {
      params.push(classId);
      enrollmentJoin += ` AND e.class_id = $${params.length}`;
    }
    if (subjectId) {
      params.push(subjectId);
      enrollmentJoin += ` AND e.subject_id = $${params.length}`;
    }

    const sql = `
      SELECT u.institutional_id,
             u.display_name,
             COALESCE(SUM(CASE WHEN ar.status = 'Present' THEN 1 ELSE 0 END), 0)::int AS present_count,
             COALESCE(SUM(CASE WHEN ar.status = 'Absent' THEN 1 ELSE 0 END), 0)::int AS absent_count,
             COALESCE(SUM(CASE WHEN ar.status = 'Excused' THEN 1 ELSE 0 END), 0)::int AS excused_count
      FROM enrollments e
      INNER JOIN users u ON u.id = e.student_id
      ${sessionJoin}
      LEFT JOIN attendance_records ar ON ar.session_id = s.id AND ar.student_id = e.student_id
      WHERE 1=1 ${enrollmentJoin}
      GROUP BY u.id, u.institutional_id, u.display_name
      ORDER BY u.display_name`;

    const result = await this.db.query<SummaryAggRow>(sql, params);
    const sessionsHeld = await this.countClosedSessions(filters, classId, subjectId);

    return result.rows.map((row) => {
      const presentCount = Number(row.present_count);
      return {
        institutionalId: row.institutional_id,
        displayName: row.display_name,
        presentCount,
        absentCount: Number(row.absent_count),
        excusedCount: Number(row.excused_count),
        attendanceRate: computeRate(presentCount, sessionsHeld),
      };
    });
  }

  async getClassSubjectSummary(
    filters: ReportFilter,
    classId?: string,
    subjectId?: string,
    classCode?: string | null,
    subjectCode?: string | null,
  ): Promise<ClassSubjectSummaryDto> {
    const sessionsHeld = await this.countClosedSessions(filters, classId, subjectId);
    const students = await this.aggregateStudentSummary(filters, classId, subjectId);

    return {
      classCode: classCode ?? null,
      subjectCode: subjectCode ?? null,
      dateFrom: filters.from,
      dateTo: filters.to,
      sessionsHeld,
      students,
    };
  }

  async listExportRows(
    filters: ReportFilter,
    classId?: string,
    subjectId?: string,
  ): Promise<CsvExportRow[]> {
    const params: unknown[] = [filters.from, filters.to, SessionStatus.Closed];
    let sql = `
      SELECT u.institutional_id, u.display_name, c.code AS class_code, sub.code AS subject_code,
             DATE(s.scheduled_start AT TIME ZONE 'UTC') AS session_date,
             ar.status, ar.checked_in_at
      FROM attendance_records ar
      INNER JOIN sessions s ON s.id = ar.session_id
      INNER JOIN classes c ON c.id = s.class_id
      INNER JOIN subjects sub ON sub.id = s.subject_id
      INNER JOIN users u ON u.id = ar.student_id
      WHERE s.status = $3
        AND DATE(s.scheduled_start AT TIME ZONE 'UTC') >= $1::date
        AND DATE(s.scheduled_start AT TIME ZONE 'UTC') <= $2::date`;

    if (classId) {
      params.push(classId);
      sql += ` AND s.class_id = $${params.length}`;
    }
    if (subjectId) {
      params.push(subjectId);
      sql += ` AND s.subject_id = $${params.length}`;
    }

    sql += ` ORDER BY session_date, c.code, sub.code, u.display_name`;

    const result = await this.db.query<CsvRow>(sql, params);
    return result.rows.map((row) => ({
      institutionalId: row.institutional_id,
      displayName: row.display_name,
      classCode: row.class_code,
      subjectCode: row.subject_code,
      sessionDate:
        row.session_date instanceof Date
          ? row.session_date.toISOString().slice(0, 10)
          : String(row.session_date).slice(0, 10),
      attendanceStatus: row.status,
      checkedInAt: row.checked_in_at?.toISOString() ?? null,
    }));
  }
}

export class ExportAuditRepository {
  constructor(private readonly db: DbPool) {}

  async insertSuccess(input: {
    adminId: string;
    filterSummary: Record<string, unknown>;
    rowCount: number;
  }): Promise<string> {
    const id = randomUUID();
    await this.db.query(
      `INSERT INTO export_audit_logs (id, admin_id, filter_summary, row_count)
       VALUES ($1, $2, $3, $4)`,
      [id, input.adminId, JSON.stringify(input.filterSummary), input.rowCount],
    );
    return id;
  }

  async countByAdmin(adminId: string): Promise<number> {
    const result = await this.db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM export_audit_logs WHERE admin_id = $1`,
      [adminId],
    );
    return Number(result.rows[0]?.count ?? 0);
  }

  async findLatestByAdmin(adminId: string): Promise<{
    adminId: string;
    filterSummary: Record<string, unknown>;
    rowCount: number;
  } | null> {
    const result = await this.db.query<{
      admin_id: string;
      filter_summary: Record<string, unknown>;
      row_count: number;
    }>(
      `SELECT admin_id, filter_summary, row_count
       FROM export_audit_logs
       WHERE admin_id = $1
       ORDER BY exported_at DESC
       LIMIT 1`,
      [adminId],
    );
    const row = result.rows[0];
    if (!row) {
      return null;
    }
    return {
      adminId: row.admin_id,
      filterSummary: row.filter_summary,
      rowCount: row.row_count,
    };
  }
}

export class ExportSecurityAuditRepository {
  constructor(private readonly db: DbPool) {}

  async logExportDenied(actorId: string, filterSummary: ReportFilter): Promise<void> {
    await this.db.query(
      `INSERT INTO security_audit_logs (id, event_type, session_id, qr_token_id, student_id, details)
       VALUES ($1, 'ExportDenied', NULL, NULL, NULL, $2)`,
      [
        randomUUID(),
        JSON.stringify({
          actorId,
          reason: "ExportNotAllowed",
          filterSummary,
        }),
      ],
    );
  }

  async countExportDenied(actorId: string): Promise<number> {
    const result = await this.db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count
       FROM security_audit_logs
       WHERE event_type = 'ExportDenied'
         AND details->>'actorId' = $1`,
      [actorId],
    );
    return Number(result.rows[0]?.count ?? 0);
  }
}

export async function truncateReportingTables(db: DbPool): Promise<void> {
  await db.query("TRUNCATE export_audit_logs RESTART IDENTITY CASCADE");
}
