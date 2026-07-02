import { randomUUID } from "node:crypto";
import type pg from "pg";
import { ALL_POLICY_FIELD_OVERRIDES } from "./defaults.js";
import {
  flattenResolvedPolicy,
  indexPoliciesByScope,
  resolveEffectivePolicyFromRows,
} from "./resolver.js";
import type {
  AttendancePolicyRecord,
  EffectivePolicyValues,
  PolicyCreateInput,
  PolicyScopeType,
  PolicyUpdateInput,
  ResolvedEffectivePolicy,
  SectionHierarchy,
} from "./types.js";

type PolicyRow = {
  id: string;
  scope_type: PolicyScopeType;
  scope_id: string | null;
  check_in_opening_offset_minutes: number | null;
  present_window_minutes: number;
  late_window_minutes: number;
  auto_close_enabled: boolean;
  absence_threshold_percent: string | null;
  excused_counts_toward_threshold: boolean;
  manual_edit_window_hours: number;
  admin_approval_required: boolean;
  gps_required: boolean;
  gps_radius_meters: number | null;
  gps_min_accuracy_meters: number | null;
  effective_from: Date | null;
  effective_to: Date | null;
  is_active: boolean;
  field_overrides: Record<string, boolean>;
  created_at: Date;
};

function mapRow(row: PolicyRow): AttendancePolicyRecord {
  return {
    id: row.id,
    scopeType: row.scope_type,
    scopeId: row.scope_id,
    checkInOpeningOffsetMinutes: row.check_in_opening_offset_minutes,
    presentWindowMinutes: row.present_window_minutes,
    lateWindowMinutes: row.late_window_minutes,
    autoCloseEnabled: row.auto_close_enabled,
    absenceThresholdPercent:
      row.absence_threshold_percent === null ? null : Number(row.absence_threshold_percent),
    excusedCountsTowardThreshold: row.excused_counts_toward_threshold,
    manualEditWindowHours: row.manual_edit_window_hours,
    adminApprovalRequired: row.admin_approval_required,
    gpsRequired: row.gps_required,
    gpsRadiusMeters: row.gps_radius_meters,
    gpsMinAccuracyMeters: row.gps_min_accuracy_meters,
    effectiveFrom: row.effective_from?.toISOString().slice(0, 10) ?? null,
    effectiveTo: row.effective_to?.toISOString().slice(0, 10) ?? null,
    isActive: row.is_active,
    fieldOverrides: row.field_overrides ?? {},
    createdAt: row.created_at.toISOString(),
  };
}

function toApiPolicy(record: AttendancePolicyRecord) {
  return {
    id: record.id,
    scopeType: record.scopeType,
    scopeId: record.scopeId,
    checkInOpeningOffsetMinutes: record.checkInOpeningOffsetMinutes,
    presentWindowMinutes: record.presentWindowMinutes,
    lateWindowMinutes: record.lateWindowMinutes,
    autoCloseEnabled: record.autoCloseEnabled,
    absenceThresholdPercent: record.absenceThresholdPercent,
    excusedCountsTowardThreshold: record.excusedCountsTowardThreshold,
    manualEditWindowHours: record.manualEditWindowHours,
    adminApprovalRequired: record.adminApprovalRequired,
    gpsRequired: record.gpsRequired,
    gpsRadiusMeters: record.gpsRadiusMeters,
    gpsMinAccuracyMeters: record.gpsMinAccuracyMeters,
    effectiveFrom: record.effectiveFrom,
    effectiveTo: record.effectiveTo,
    isActive: record.isActive,
    createdAt: record.createdAt,
  };
}

function toResolvedApi(resolved: ResolvedEffectivePolicy) {
  const values = flattenResolvedPolicy(resolved);
  const sources: Record<string, PolicyScopeType> = {};
  for (const [key, field] of Object.entries(resolved)) {
    sources[key] = field.source;
  }
  return { values, sources };
}

export function createPolicyEngineRepository(pool: pg.Pool) {
  async function loadSectionHierarchy(
    client: pg.Pool | pg.PoolClient,
    classSectionId: string,
  ): Promise<SectionHierarchy | null> {
    const result = await client.query<{ course_id: string; faculty_id: string }>(
      `
      SELECT cs.course_id, c.faculty_id
      FROM class_sections cs
      JOIN courses c ON c.id = cs.course_id
      WHERE cs.id = $1
      `,
      [classSectionId],
    );
    const row = result.rows[0];
    if (!row) return null;
    return {
      classSectionId,
      courseId: row.course_id,
      facultyId: row.faculty_id,
    };
  }

  async function loadPoliciesForHierarchy(
    client: pg.Pool | pg.PoolClient,
    hierarchy: SectionHierarchy,
    at: Date = new Date(),
  ): Promise<AttendancePolicyRecord[]> {
    const result = await client.query<PolicyRow>(
      `
      SELECT *
      FROM attendance_policies
      WHERE is_active = true
        AND (
          (scope_type = 'Institution' AND scope_id IS NULL)
          OR (scope_type = 'Faculty' AND scope_id = $1)
          OR (scope_type = 'Course' AND scope_id = $2)
          OR (scope_type = 'ClassSection' AND scope_id = $3)
        )
        AND (effective_from IS NULL OR effective_from <= $4::date)
        AND (effective_to IS NULL OR effective_to >= $4::date)
      `,
      [hierarchy.facultyId, hierarchy.courseId, hierarchy.classSectionId, at],
    );
    return result.rows.map(mapRow);
  }

  async function resolveEffectivePolicy(
    classSectionId: string,
    at: Date = new Date(),
    client?: pg.PoolClient,
  ): Promise<ResolvedEffectivePolicy | null> {
    const db = client ?? pool;
    const hierarchy = await loadSectionHierarchy(db, classSectionId);
    if (!hierarchy) return null;

    const rows = await loadPoliciesForHierarchy(db, hierarchy, at);
    const indexed = indexPoliciesByScope(rows, hierarchy);
    return resolveEffectivePolicyFromRows(indexed);
  }

  async function resolveEffectivePolicyValues(
    classSectionId: string,
    at: Date = new Date(),
    client?: pg.PoolClient,
  ): Promise<EffectivePolicyValues | null> {
    const resolved = await resolveEffectivePolicy(classSectionId, at, client);
    return resolved ? flattenResolvedPolicy(resolved) : null;
  }

  async function savePolicySnapshot(
    client: pg.PoolClient,
    classSessionId: string,
    classSectionId: string,
    at: Date = new Date(),
  ): Promise<void> {
    const resolved = await resolveEffectivePolicy(classSectionId, at, client);
    if (!resolved) return;

    await client.query(
      `
      INSERT INTO policy_snapshots (id, class_session_id, resolved_json, resolved_at)
      VALUES ($1, $2, $3::jsonb, $4)
      `,
      [randomUUID(), classSessionId, JSON.stringify(toResolvedApi(resolved)), at],
    );
  }

  async function writePolicyAudit(params: {
    actorUserId: string;
    policyId: string;
    oldValue: Record<string, unknown> | null;
    newValue: Record<string, unknown>;
    reason?: string;
    correlationId?: string | null;
  }): Promise<void> {
    await pool.query(
      `
      INSERT INTO audit_logs (
        id, actor_user_id, action_type, target_type, target_id, old_value, new_value, reason, correlation_id
      )
      VALUES ($1, $2, 'PolicyChange', 'AttendancePolicy', $3, $4::jsonb, $5::jsonb, $6, $7)
      `,
      [
        randomUUID(),
        params.actorUserId,
        params.policyId,
        params.oldValue ? JSON.stringify(params.oldValue) : null,
        JSON.stringify(params.newValue),
        params.reason ?? null,
        params.correlationId ?? null,
      ],
    );
  }

  function recordToEffectiveValues(record: AttendancePolicyRecord): EffectivePolicyValues {
    return {
      checkInOpeningOffsetMinutes: record.checkInOpeningOffsetMinutes,
      presentWindowMinutes: record.presentWindowMinutes,
      lateWindowMinutes: record.lateWindowMinutes,
      autoCloseEnabled: record.autoCloseEnabled,
      absenceThresholdPercent: record.absenceThresholdPercent,
      excusedCountsTowardThreshold: record.excusedCountsTowardThreshold,
      manualEditWindowHours: record.manualEditWindowHours,
      adminApprovalRequired: record.adminApprovalRequired,
      gpsRequired: record.gpsRequired,
      gpsRadiusMeters: record.gpsRadiusMeters,
      gpsMinAccuracyMeters: record.gpsMinAccuracyMeters,
    };
  }

  async function createPolicy(input: PolicyCreateInput): Promise<AttendancePolicyRecord> {
    const id = randomUUID();
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      await deactivatePoliciesAtScope(input.scopeType, input.scopeId ?? null, client);

      const result = await client.query<PolicyRow>(
      `
      INSERT INTO attendance_policies (
        id, scope_type, scope_id,
        check_in_opening_offset_minutes, present_window_minutes, late_window_minutes,
        auto_close_enabled, absence_threshold_percent, excused_counts_toward_threshold,
        manual_edit_window_hours, admin_approval_required,
        gps_required, gps_radius_meters, gps_min_accuracy_meters,
        effective_from, effective_to, is_active, field_overrides
      )
      VALUES (
        $1, $2, $3,
        $4, $5, $6,
        $7, $8, $9,
        $10, $11,
        $12, $13, $14,
        $15, $16, true, $17::jsonb
      )
      RETURNING *
      `,
      [
        id,
        input.scopeType,
        input.scopeId,
        input.checkInOpeningOffsetMinutes,
        input.presentWindowMinutes,
        input.lateWindowMinutes,
        input.autoCloseEnabled ?? true,
        input.absenceThresholdPercent,
        input.excusedCountsTowardThreshold ?? false,
        input.manualEditWindowHours,
        input.adminApprovalRequired ?? false,
        input.gpsRequired ?? false,
        input.gpsRadiusMeters,
        input.gpsMinAccuracyMeters,
        input.effectiveFrom,
        input.effectiveTo,
        JSON.stringify(input.fieldOverrides),
      ],
    );
      await client.query("COMMIT");
      return mapRow(result.rows[0]!);
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async function getPolicyById(policyId: string): Promise<AttendancePolicyRecord | null> {
    const result = await pool.query<PolicyRow>(
      `SELECT * FROM attendance_policies WHERE id = $1`,
      [policyId],
    );
    const row = result.rows[0];
    return row ? mapRow(row) : null;
  }

  async function updatePolicy(
    policyId: string,
    input: PolicyUpdateInput,
    current: AttendancePolicyRecord,
  ): Promise<AttendancePolicyRecord | null> {
    const mergedOverrides = {
      ...current.fieldOverrides,
      ...(input.fieldOverrides ?? {}),
    };

    const result = await pool.query<PolicyRow>(
      `
      UPDATE attendance_policies
      SET
        check_in_opening_offset_minutes = COALESCE($2, check_in_opening_offset_minutes),
        present_window_minutes = COALESCE($3, present_window_minutes),
        late_window_minutes = COALESCE($4, late_window_minutes),
        auto_close_enabled = COALESCE($5, auto_close_enabled),
        absence_threshold_percent = COALESCE($6, absence_threshold_percent),
        excused_counts_toward_threshold = COALESCE($7, excused_counts_toward_threshold),
        manual_edit_window_hours = COALESCE($8, manual_edit_window_hours),
        admin_approval_required = COALESCE($9, admin_approval_required),
        gps_required = COALESCE($10, gps_required),
        gps_radius_meters = CASE WHEN $10 IS NOT NULL THEN $11 ELSE gps_radius_meters END,
        gps_min_accuracy_meters = COALESCE($12, gps_min_accuracy_meters),
        effective_from = COALESCE($13, effective_from),
        effective_to = COALESCE($14, effective_to),
        field_overrides = $15::jsonb
      WHERE id = $1
      RETURNING *
      `,
      [
        policyId,
        input.checkInOpeningOffsetMinutes,
        input.presentWindowMinutes,
        input.lateWindowMinutes,
        input.autoCloseEnabled,
        input.absenceThresholdPercent,
        input.excusedCountsTowardThreshold,
        input.manualEditWindowHours,
        input.adminApprovalRequired,
        input.gpsRequired,
        input.gpsRadiusMeters,
        input.gpsMinAccuracyMeters,
        input.effectiveFrom,
        input.effectiveTo,
        JSON.stringify(mergedOverrides),
      ],
    );
    const row = result.rows[0];
    return row ? mapRow(row) : null;
  }

  async function listPolicies(params: {
    page: number;
    pageSize: number;
    scopeType?: PolicyScopeType;
  }): Promise<{ items: AttendancePolicyRecord[]; totalItems: number }> {
    const offset = (params.page - 1) * params.pageSize;
    const filters: string[] = ["is_active = true"];
    const values: unknown[] = [];
    let paramIndex = 1;

    if (params.scopeType) {
      filters.push(`scope_type = $${paramIndex++}`);
      values.push(params.scopeType);
    }

    const where = filters.length ? `WHERE ${filters.join(" AND ")}` : "";

    const countResult = await pool.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM attendance_policies ${where}`,
      values,
    );
    const totalItems = Number(countResult.rows[0]?.count ?? 0);

    const listResult = await pool.query<PolicyRow>(
      `
      SELECT *
      FROM attendance_policies
      ${where}
      ORDER BY created_at DESC
      LIMIT $${paramIndex++} OFFSET $${paramIndex}
      `,
      [...values, params.pageSize, offset],
    );

    return {
      items: listResult.rows.map(mapRow),
      totalItems,
    };
  }

  async function deactivatePoliciesAtScope(
    scopeType: PolicyScopeType,
    scopeId: string | null,
    client: pg.PoolClient,
  ): Promise<void> {
    if (scopeType === "Institution") {
      await client.query(
        `
        UPDATE attendance_policies
        SET is_active = false
        WHERE scope_type = 'Institution' AND scope_id IS NULL AND is_active = true
        `,
      );
    } else {
      await client.query(
        `
        UPDATE attendance_policies
        SET is_active = false
        WHERE scope_type = $1 AND scope_id = $2 AND is_active = true
        `,
        [scopeType, scopeId],
      );
    }
  }

  return {
    loadSectionHierarchy,
    loadPoliciesForHierarchy,
    resolveEffectivePolicy,
    resolveEffectivePolicyValues,
    savePolicySnapshot,
    writePolicyAudit,
    createPolicy,
    getPolicyById,
    updatePolicy,
    listPolicies,
    deactivatePoliciesAtScope,
    toApiPolicy,
    toResolvedApi,
    recordToEffectiveValues,
    ALL_POLICY_FIELD_OVERRIDES,
    pool,
  };
}

export type PolicyEngineRepository = ReturnType<typeof createPolicyEngineRepository>;
