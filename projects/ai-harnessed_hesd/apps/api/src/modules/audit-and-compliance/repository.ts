import type pg from "pg";
import type { AuditLogEntry, AuditLogQueryFilters, ResolvedAuditReadScope } from "./types.js";
import {
  apiActionTypeToDbFilter,
  deriveApiActionType,
  extractStatus,
} from "./validation.js";

type AuditRow = {
  id: string;
  timestamp: Date;
  actor_user_id: string | null;
  action_type: string;
  target_type: string;
  target_id: string;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  reason: string | null;
  scope_type: string | null;
  scope_id: string | null;
  correlation_id: string | null;
  actor_display_name: string | null;
  ar_student_user_id: string | null;
  ar_class_session_id: string | null;
  ar_class_section_id: string | null;
  cia_student_user_id: string | null;
  cia_class_session_id: string | null;
  cia_class_section_id: string | null;
};

function mapRow(row: AuditRow): AuditLogEntry {
  const newValue = row.new_value;
  const apiAction = deriveApiActionType({
    action_type: row.action_type,
    actor_user_id: row.actor_user_id,
    new_value: newValue,
  });

  const studentUserId =
    (typeof newValue?.studentUserId === "string" ? newValue.studentUserId : null) ??
    row.ar_student_user_id ??
    row.cia_student_user_id;
  const classSessionId =
    (typeof newValue?.classSessionId === "string" ? newValue.classSessionId : null) ??
    row.ar_class_session_id ??
    row.cia_class_session_id;
  const classSectionId =
    (typeof newValue?.classSectionId === "string" ? newValue.classSectionId : null) ??
    row.ar_class_section_id ??
    row.cia_class_section_id;

  const actorRole =
    typeof newValue?.actorRole === "string"
      ? newValue.actorRole
      : row.new_value?.actorRole
        ? String(row.new_value.actorRole)
        : null;

  let scopeFilterSummary: string | null = null;
  let format: string | null = null;
  if (row.action_type === "Export" && newValue) {
    format = typeof newValue.format === "string" ? newValue.format : null;
    const filters = newValue.filters as Record<string, unknown> | undefined;
    if (filters) {
      const parts: string[] = [];
      if (typeof filters.termId === "string") parts.push(`termId=${filters.termId}`);
      if (typeof filters.classSectionId === "string") {
        parts.push(`classSectionId=${filters.classSectionId}`);
      }
      scopeFilterSummary = parts.join(", ") || null;
    } else if (row.scope_type === "ClassSection" && row.scope_id) {
      scopeFilterSummary = `classSectionId=${row.scope_id}`;
    }
  }

  return {
    id: row.id,
    actionType: apiAction,
    actorUserId: row.actor_user_id,
    actorRole,
    actorDisplayName: row.actor_display_name,
    targetType: row.target_type,
    targetId: row.target_id,
    studentUserId,
    classSessionId,
    classSectionId,
    oldStatus: extractStatus(row.old_value),
    newStatus: extractStatus(row.new_value),
    outcome: typeof newValue?.outcome === "string" ? newValue.outcome : null,
    reason: row.reason,
    scopeFilterSummary,
    format,
    correlationId: row.correlation_id,
    occurredAt: row.timestamp.toISOString(),
  };
}

export function createAuditRepository(pool: pg.Pool) {
  return {
    async queryAuditLogs(
      filters: AuditLogQueryFilters,
      readScope: ResolvedAuditReadScope,
    ): Promise<{ items: AuditLogEntry[]; totalItems: number }> {
      const conditions: string[] = [];
      const params: unknown[] = [];
      let paramIndex = 1;

      if (!readScope.institutionWide && readScope.classSectionIds) {
        conditions.push(
          `(
            ar.class_section_id = ANY($${paramIndex}::uuid[])
            OR cia_cs.class_section_id = ANY($${paramIndex}::uuid[])
            OR (al.scope_type = 'ClassSection' AND al.scope_id = ANY($${paramIndex}::uuid[]))
            OR (al.new_value->>'classSectionId')::uuid = ANY($${paramIndex}::uuid[])
          )`,
        );
        params.push(readScope.classSectionIds);
        paramIndex += 1;
      }

      if (filters.actorUserId) {
        conditions.push(`al.actor_user_id = $${paramIndex}`);
        params.push(filters.actorUserId);
        paramIndex += 1;
      }

      if (filters.targetType) {
        conditions.push(`al.target_type = $${paramIndex}`);
        params.push(filters.targetType);
        paramIndex += 1;
      }

      if (filters.targetId) {
        conditions.push(
          `(
            al.target_id = $${paramIndex}::uuid
            OR ar.student_user_id = $${paramIndex}::uuid
            OR cia.student_user_id = $${paramIndex}::uuid
            OR (al.new_value->>'studentUserId')::uuid = $${paramIndex}::uuid
          )`,
        );
        params.push(filters.targetId);
        paramIndex += 1;
      }

      if (filters.classSessionId) {
        conditions.push(
          `(
            ar.class_session_id = $${paramIndex}::uuid
            OR cia.class_session_id = $${paramIndex}::uuid
            OR (al.new_value->>'classSessionId')::uuid = $${paramIndex}::uuid
          )`,
        );
        params.push(filters.classSessionId);
        paramIndex += 1;
      }

      if (filters.classSectionId) {
        conditions.push(
          `(
            ar.class_section_id = $${paramIndex}::uuid
            OR cia_cs.class_section_id = $${paramIndex}::uuid
            OR (al.scope_type = 'ClassSection' AND al.scope_id = $${paramIndex}::uuid)
            OR (al.new_value->>'classSectionId')::uuid = $${paramIndex}::uuid
          )`,
        );
        params.push(filters.classSectionId);
        paramIndex += 1;
      }

      if (filters.actionType) {
        const mapped = apiActionTypeToDbFilter(filters.actionType);
        conditions.push(`al.action_type = ANY($${paramIndex}::text[])`);
        params.push(mapped.dbActionTypes);
        paramIndex += 1;
        if (mapped.attendanceSubtype) {
          conditions.push(`al.new_value->>'auditActionSubtype' = $${paramIndex}`);
          params.push(mapped.attendanceSubtype);
          paramIndex += 1;
        }
      }

      if (filters.from) {
        conditions.push(`al.timestamp >= $${paramIndex}::timestamptz`);
        params.push(filters.from);
        paramIndex += 1;
      }

      if (filters.to) {
        conditions.push(`al.timestamp <= $${paramIndex}::timestamptz`);
        params.push(filters.to);
        paramIndex += 1;
      }

      if (readScope.technicalOnly) {
        conditions.push(`al.action_type = ANY($${paramIndex}::text[])`);
        params.push(["SessionOpen", "SessionClose", "PolicyChange", "EnrollmentImport"]);
        paramIndex += 1;
      }

      const whereClause = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

      const baseFrom = `
        FROM audit_logs al
        LEFT JOIN users u ON u.id = al.actor_user_id
        LEFT JOIN attendance_records ar ON al.target_type = 'AttendanceRecord' AND ar.id = al.target_id
        LEFT JOIN check_in_attempts cia ON al.target_type = 'CheckInAttempt' AND cia.id = al.target_id
        LEFT JOIN class_sessions cia_cs ON cia.class_session_id = cia_cs.id
      `;

      const countResult = await pool.query<{ count: string }>(
        `SELECT COUNT(DISTINCT al.id)::text AS count ${baseFrom} ${whereClause}`,
        params,
      );
      const totalItems = Number.parseInt(countResult.rows[0]?.count ?? "0", 10);

      const offset = (filters.page - 1) * filters.pageSize;
      const listParams = [...params, filters.pageSize, offset];
      const limitParam = paramIndex;
      const offsetParam = paramIndex + 1;

      const listResult = await pool.query<AuditRow>(
        `
        SELECT
          al.id,
          al.timestamp,
          al.actor_user_id,
          al.action_type,
          al.target_type,
          al.target_id,
          al.old_value,
          al.new_value,
          al.reason,
          al.scope_type,
          al.scope_id,
          al.correlation_id,
          u.display_name AS actor_display_name,
          ar.student_user_id AS ar_student_user_id,
          ar.class_session_id AS ar_class_session_id,
          ar.class_section_id AS ar_class_section_id,
          cia.student_user_id AS cia_student_user_id,
          cia.class_session_id AS cia_class_session_id,
          cia_cs.class_section_id AS cia_class_section_id
        ${baseFrom}
        ${whereClause}
        ORDER BY al.timestamp DESC
        LIMIT $${limitParam} OFFSET $${offsetParam}
        `,
        listParams,
      );

      return {
        items: listResult.rows.map(mapRow),
        totalItems,
      };
    },
  };
}

export type AuditRepository = ReturnType<typeof createAuditRepository>;
