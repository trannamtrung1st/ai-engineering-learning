import { randomUUID } from "node:crypto";
import type pg from "pg";
import { writeAuditEvent } from "../audit-and-compliance/service.js";
import type { ActorContext } from "../identity/types.js";
import type {
  AttendanceReportFilters,
  AttendanceReportRow,
  ExportFormat,
  ExportJobResult,
  ReportSortField,
  ResolvedReportScope,
} from "./types.js";

const CSV_HEADERS = [
  "studentCode",
  "studentUserId",
  "classSectionId",
  "sectionCode",
  "classSessionId",
  "sessionDate",
  "attendanceStatus",
  "checkInAt",
  "checkInMethod",
] as const;

function escapeCsv(value: string): string {
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function rowsToCsv(rows: AttendanceReportRow[]): string {
  const lines = [CSV_HEADERS.join(",")];
  for (const row of rows) {
    lines.push(
      [
        row.studentCode,
        row.studentUserId,
        row.classSectionId,
        row.sectionCode,
        row.classSessionId,
        row.sessionDate,
        row.attendanceStatus,
        row.checkInAt ?? "",
        row.checkInMethod ?? "",
      ]
        .map((v) => escapeCsv(String(v)))
        .join(","),
    );
  }
  return lines.join("\n");
}

function sortClause(sortBy: ReportSortField, sortOrder: "asc" | "desc"): string {
  const direction = sortOrder === "asc" ? "ASC" : "DESC";
  switch (sortBy) {
    case "status":
      return `ar.status ${direction}, sess.scheduled_start_at DESC`;
    case "classSectionId":
      return `ar.class_section_id ${direction}, sess.scheduled_start_at DESC`;
    default:
      return `sess.scheduled_start_at ${direction}, sp.student_code ASC`;
  }
}

export function createReportingRepository(pool: pg.Pool) {
  return {
    async queryAttendanceReport(params: {
      scope: ResolvedReportScope;
      filters: AttendanceReportFilters;
      sortBy: ReportSortField;
      sortOrder: "asc" | "desc";
      page: number;
      pageSize: number;
    }): Promise<{ rows: AttendanceReportRow[]; totalItems: number }> {
      const conditions: string[] = ["1=1"];
      const values: unknown[] = [];
      let paramIndex = 1;

      if (params.scope.classSectionIds !== null) {
        conditions.push(`ar.class_section_id = ANY($${paramIndex}::uuid[])`);
        values.push(params.scope.classSectionIds);
        paramIndex += 1;
      }

      const { filters } = params;
      if (filters.termId) {
        conditions.push(`cs.term_id = $${paramIndex}`);
        values.push(filters.termId);
        paramIndex += 1;
      }
      if (filters.courseId) {
        conditions.push(`cs.course_id = $${paramIndex}`);
        values.push(filters.courseId);
        paramIndex += 1;
      }
      if (filters.lecturerUserId) {
        conditions.push(`cs.lecturer_user_id = $${paramIndex}`);
        values.push(filters.lecturerUserId);
        paramIndex += 1;
      }
      if (filters.studentUserId) {
        conditions.push(`ar.student_user_id = $${paramIndex}`);
        values.push(filters.studentUserId);
        paramIndex += 1;
      }
      if (filters.status) {
        conditions.push(`ar.status = $${paramIndex}`);
        values.push(filters.status);
        paramIndex += 1;
      }
      if (filters.from) {
        conditions.push(`sess.scheduled_start_at >= $${paramIndex}::timestamptz`);
        values.push(filters.from);
        paramIndex += 1;
      }
      if (filters.to) {
        conditions.push(`sess.scheduled_start_at <= $${paramIndex}::timestamptz`);
        values.push(filters.to);
        paramIndex += 1;
      }
      if (filters.search) {
        conditions.push(
          `(sp.student_code ILIKE $${paramIndex} OR u.display_name ILIKE $${paramIndex})`,
        );
        values.push(`%${filters.search}%`);
        paramIndex += 1;
      }

      const whereClause = conditions.join(" AND ");
      const baseFrom = `
        FROM attendance_records ar
        JOIN class_sessions sess ON sess.id = ar.class_session_id
        JOIN class_sections cs ON cs.id = ar.class_section_id
        JOIN users u ON u.id = ar.student_user_id
        LEFT JOIN student_profiles sp ON sp.user_id = ar.student_user_id
        WHERE ${whereClause}
      `;

      const countResult = await pool.query<{ count: string }>(
        `SELECT COUNT(*)::text AS count ${baseFrom}`,
        values,
      );
      const totalItems = Number.parseInt(countResult.rows[0]?.count ?? "0", 10);

      const offset = (params.page - 1) * params.pageSize;
      const listValues = [...values, params.pageSize, offset];
      const limitParam = paramIndex;
      const offsetParam = paramIndex + 1;

      const listResult = await pool.query<{
        attendance_record_id: string;
        student_user_id: string;
        student_code: string | null;
        class_session_id: string;
        class_section_id: string;
        section_code: string;
        attendance_status: string;
        check_in_at: Date | null;
        check_in_method: string | null;
        session_date: Date;
      }>(
        `
        SELECT
          ar.id AS attendance_record_id,
          ar.student_user_id,
          COALESCE(sp.student_code, u.email) AS student_code,
          ar.class_session_id,
          ar.class_section_id,
          cs.section_code,
          ar.status AS attendance_status,
          ar.check_in_at,
          ar.check_in_method,
          sess.scheduled_start_at AS session_date
        ${baseFrom}
        ORDER BY ${sortClause(params.sortBy, params.sortOrder)}
        LIMIT $${limitParam} OFFSET $${offsetParam}
        `,
        listValues,
      );

      const rows: AttendanceReportRow[] = listResult.rows.map((row) => ({
        attendanceRecordId: row.attendance_record_id,
        studentUserId: row.student_user_id,
        studentCode: row.student_code ?? "",
        classSessionId: row.class_session_id,
        classSectionId: row.class_section_id,
        sectionCode: row.section_code,
        attendanceStatus: row.attendance_status,
        checkInAt: row.check_in_at ? row.check_in_at.toISOString() : null,
        checkInMethod: row.check_in_method,
        sessionDate: row.session_date.toISOString(),
      }));

      return { rows, totalItems };
    },

    async createExportJob(params: {
      actor: ActorContext;
      format: ExportFormat;
      filters: AttendanceReportFilters;
      scope: ResolvedReportScope;
      idempotencyKey?: string;
      correlationId?: string;
    }): Promise<ExportJobResult> {
      const client = await pool.connect();
      try {
        await client.query("BEGIN");

        if (params.idempotencyKey) {
          const existing = await client.query<{
            id: string;
            status: ExportJobResult["status"];
            format: ExportFormat;
            row_count: number | null;
          }>(
            `
            SELECT id, status, format, row_count
            FROM export_jobs
            WHERE actor_user_id = $1 AND idempotency_key = $2
            `,
            [params.actor.userId, params.idempotencyKey],
          );
          if (existing.rows[0]) {
            await client.query("COMMIT");
            return {
              exportJobId: existing.rows[0].id,
              status: existing.rows[0].status,
              format: existing.rows[0].format,
              rowCount: existing.rows[0].row_count ?? undefined,
            };
          }
        }

        const jobId = randomUUID();
        await client.query(
          `
          INSERT INTO export_jobs (id, actor_user_id, format, status, filters_json, idempotency_key)
          VALUES ($1, $2, $3, 'Processing', $4::jsonb, $5)
          `,
          [
            jobId,
            params.actor.userId,
            params.format,
            JSON.stringify(params.filters),
            params.idempotencyKey ?? null,
          ],
        );

        const { rows, totalItems } = await this.queryAttendanceReport({
          scope: params.scope,
          filters: params.filters,
          sortBy: "date",
          sortOrder: "desc",
          page: 1,
          pageSize: 100_000,
        });

        const csv = rowsToCsv(rows);

        await client.query(
          `
          UPDATE export_jobs
          SET status = 'Completed', artifact_csv = $2, row_count = $3, completed_at = now()
          WHERE id = $1
          `,
          [jobId, csv, totalItems],
        );

        const primaryRole = params.actor.roles[0] ?? "Lecturer";
        await writeAuditEvent(client, {
          actorUserId: params.actor.userId,
          actionType: "Export",
          targetType: "ExportJob",
          targetId: jobId,
          newValue: {
            format: params.format,
            filters: params.filters,
            rowCount: totalItems,
            actorRole: primaryRole,
          },
          reason: "Attendance CSV export completed",
          scopeType: params.scope.classSectionIds?.length === 1 ? "ClassSection" : "Institution",
          scopeId: params.scope.classSectionIds?.[0] ?? null,
          correlationId: params.correlationId ?? null,
        });

        await client.query("COMMIT");

        return {
          exportJobId: jobId,
          status: "Completed",
          format: params.format,
          rowCount: totalItems,
        };
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      } finally {
        client.release();
      }
    },

    async getExportArtifact(exportJobId: string): Promise<{ csv: string; rowCount: number } | null> {
      const result = await pool.query<{ artifact_csv: string | null; row_count: number | null }>(
        `SELECT artifact_csv, row_count FROM export_jobs WHERE id = $1 AND status = 'Completed'`,
        [exportJobId],
      );
      const row = result.rows[0];
      if (!row?.artifact_csv) return null;
      return { csv: row.artifact_csv, rowCount: row.row_count ?? 0 };
    },

    async getExportArtifactForActor(
      exportJobId: string,
      actorUserId: string,
    ): Promise<{ csv: string; rowCount: number } | null> {
      const result = await pool.query<{ artifact_csv: string | null; row_count: number | null }>(
        `
        SELECT artifact_csv, row_count
        FROM export_jobs
        WHERE id = $1 AND actor_user_id = $2 AND status = 'Completed'
        `,
        [exportJobId, actorUserId],
      );
      const row = result.rows[0];
      if (!row?.artifact_csv) return null;
      return { csv: row.artifact_csv, rowCount: row.row_count ?? 0 };
    },

    /** Test helper — reset export jobs created in a test window. */
    async deleteExportJobsForActor(actorUserId: string): Promise<void> {
      await pool.query(`DELETE FROM audit_logs WHERE target_type = 'ExportJob' AND actor_user_id = $1`, [
        actorUserId,
      ]);
      await pool.query(`DELETE FROM export_jobs WHERE actor_user_id = $1`, [actorUserId]);
    },
  };
}

export type ReportingRepository = ReturnType<typeof createReportingRepository>;
