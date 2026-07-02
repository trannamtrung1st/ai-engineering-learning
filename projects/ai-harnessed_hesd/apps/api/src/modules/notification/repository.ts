import { randomUUID } from "node:crypto";
import type pg from "pg";
import { writeAuditEvent } from "../audit-and-compliance/service.js";
import {
  indexPoliciesByScope,
  resolveEffectivePolicyFromRows,
} from "../policy-engine/resolver.js";
import { createPolicyEngineRepository } from "../policy-engine/repository.js";
import { isNotificationModuleEnabled } from "./config.js";
import {
  computeUnexcusedAbsenceRate,
  exceedsAbsenceThreshold,
  resolveConfiguredAbsenceThreshold,
  resolveExcusedCountsTowardThreshold,
  type ClosedSessionAttendanceStatus,
} from "./evaluator.js";
import type {
  AbsenceRateSnapshot,
  AbsenceThresholdAlertRow,
  EvaluateAbsenceThresholdResult,
  NotificationRecipientRole,
} from "./types.js";

type SectionContext = {
  id: string;
  sectionCode: string;
  lecturerUserId: string;
};

export function createNotificationRepository(pool: pg.Pool) {
  const policyEngine = createPolicyEngineRepository(pool);

  async function loadSectionContext(classSectionId: string): Promise<SectionContext | null> {
    const result = await pool.query<{
      id: string;
      section_code: string;
      lecturer_user_id: string;
    }>(
      `
      SELECT id, section_code, lecturer_user_id
      FROM class_sections
      WHERE id = $1
      `,
      [classSectionId],
    );
    const row = result.rows[0];
    if (!row) return null;
    return {
      id: row.id,
      sectionCode: row.section_code,
      lecturerUserId: row.lecturer_user_id,
    };
  }

  async function loadClosedAttendanceStatuses(
    classSectionId: string,
    studentUserId: string,
    client?: pg.Pool | pg.PoolClient,
  ): Promise<ClosedSessionAttendanceStatus[]> {
    const db = client ?? pool;
    const result = await db.query<{ status: ClosedSessionAttendanceStatus }>(
      `
      SELECT ar.status
      FROM attendance_records ar
      JOIN class_sessions cs ON cs.id = ar.class_session_id
      WHERE cs.class_section_id = $1
        AND cs.state = 'Closed'
        AND ar.student_user_id = $2
      ORDER BY cs.scheduled_start_at
      `,
      [classSectionId, studentUserId],
    );
    return result.rows.map((row) => row.status);
  }

  async function listEnrolledStudentIds(classSectionId: string): Promise<string[]> {
    const result = await pool.query<{ student_user_id: string }>(
      `
      SELECT student_user_id
      FROM enrollments
      WHERE class_section_id = $1
        AND status = 'Active'
      `,
      [classSectionId],
    );
    return result.rows.map((row) => row.student_user_id);
  }

  async function hasExistingAbsenceAlert(
    classSectionId: string,
    studentUserId: string,
    client?: pg.Pool | pg.PoolClient,
  ): Promise<boolean> {
    const db = client ?? pool;
    const result = await db.query(
      `
      SELECT 1
      FROM policy_alert_events
      WHERE class_section_id = $1
        AND student_user_id = $2
        AND alert_type = 'AbsenceThreshold'
      LIMIT 1
      `,
      [classSectionId, studentUserId],
    );
    return (result.rowCount ?? 0) > 0;
  }

  async function listAcademicAdminUserIds(): Promise<string[]> {
    const result = await pool.query<{ user_id: string }>(
      `
      SELECT DISTINCT user_id
      FROM user_role_assignments
      WHERE role = 'AcademicAdmin'
      `,
    );
    return result.rows.map((row) => row.user_id);
  }

  async function computeAbsenceSnapshot(
    classSectionId: string,
    studentUserId: string,
    at: Date = new Date(),
    client?: pg.Pool | pg.PoolClient,
  ): Promise<AbsenceRateSnapshot | null> {
    const hierarchy = await policyEngine.loadSectionHierarchy(pool, classSectionId);
    if (!hierarchy) return null;

    const db = client ?? pool;
    const policyRows = await policyEngine.loadPoliciesForHierarchy(db, hierarchy, at);
    const indexed = indexPoliciesByScope(policyRows, hierarchy);
    const threshold = resolveConfiguredAbsenceThreshold(indexed);
    if (threshold === null) {
      return null;
    }

    const excusedCountsTowardThreshold = resolveExcusedCountsTowardThreshold(
      indexed,
      resolveEffectivePolicyFromRows(indexed).excusedCountsTowardThreshold.value,
    );
    const statuses = await loadClosedAttendanceStatuses(classSectionId, studentUserId, db);
    const computation = computeUnexcusedAbsenceRate(statuses, excusedCountsTowardThreshold);

    return {
      unexcusedAbsenceRate: computation.unexcusedAbsenceRate,
      absenceThresholdPercent: threshold,
      excusedCountsTowardThreshold,
      eligibleSessionCount: computation.eligibleSessionCount,
      unexcusedAbsentCount: computation.unexcusedAbsentCount,
    };
  }

  async function evaluateAbsenceThreshold(
    classSectionId: string,
    studentUserId: string,
    options: { correlationId?: string | null; actorUserId?: string | null } = {},
  ): Promise<EvaluateAbsenceThresholdResult | null> {
    if (!isNotificationModuleEnabled()) {
      return null;
    }

    const section = await loadSectionContext(classSectionId);
    if (!section) return null;

    const snapshot = await computeAbsenceSnapshot(classSectionId, studentUserId);
    if (!snapshot) {
      return {
        alertEmitted: false,
        snapshot: {
          unexcusedAbsenceRate: 0,
          absenceThresholdPercent: 0,
          excusedCountsTowardThreshold: false,
          eligibleSessionCount: 0,
          unexcusedAbsentCount: 0,
        },
      };
    }

    if (!exceedsAbsenceThreshold(snapshot.unexcusedAbsenceRate, snapshot.absenceThresholdPercent)) {
      return { alertEmitted: false, snapshot };
    }

    if (await hasExistingAbsenceAlert(classSectionId, studentUserId)) {
      return { alertEmitted: false, snapshot };
    }

    const alertEventId = randomUUID();
    const recipients: { userId: string; role: NotificationRecipientRole }[] = [
      { userId: studentUserId, role: "Student" },
      { userId: section.lecturerUserId, role: "Lecturer" },
    ];

    for (const adminUserId of await listAcademicAdminUserIds()) {
      recipients.push({ userId: adminUserId, role: "AcademicAdmin" });
    }

    const alertPayload = {
      sectionCode: section.sectionCode,
      studentUserId,
      classSectionId,
      unexcusedAbsenceRate: snapshot.unexcusedAbsenceRate,
      absenceThresholdPercent: snapshot.absenceThresholdPercent,
      recipients: recipients.map((recipient) => ({
        userId: recipient.userId,
        role: recipient.role,
      })),
    };

    const client = await pool.connect();
    try {
      await client.query("BEGIN");

      const insertResult = await client.query<{ id: string }>(
        `
        INSERT INTO policy_alert_events (
          id, class_section_id, student_user_id, alert_type,
          unexcused_absence_rate, absence_threshold_percent, payload
        )
        VALUES ($1, $2, $3, 'AbsenceThreshold', $4, $5, $6::jsonb)
        ON CONFLICT (class_section_id, student_user_id, alert_type) DO NOTHING
        RETURNING id
        `,
        [
          alertEventId,
          classSectionId,
          studentUserId,
          snapshot.unexcusedAbsenceRate,
          snapshot.absenceThresholdPercent,
          JSON.stringify(alertPayload),
        ],
      );

      if ((insertResult.rowCount ?? 0) === 0) {
        await client.query("ROLLBACK");
        return { alertEmitted: false, snapshot };
      }

      const persistedAlertId = insertResult.rows[0]!.id;

      for (const recipient of recipients) {
        await client.query(
          `
          INSERT INTO notification_delivery_queue (
            id, alert_event_id, recipient_user_id, recipient_role, payload
          )
          VALUES ($1, $2, $3, $4, $5::jsonb)
          `,
          [
            randomUUID(),
            persistedAlertId,
            recipient.userId,
            recipient.role,
            JSON.stringify({
              sectionCode: section.sectionCode,
              studentUserId,
              unexcusedAbsenceRate: snapshot.unexcusedAbsenceRate,
              absenceThresholdPercent: snapshot.absenceThresholdPercent,
            }),
          ],
        );
      }

      await writeAuditEvent(client, {
        actorUserId: options.actorUserId ?? null,
        actionType: "AbsenceThresholdAlert",
        targetType: "Student",
        targetId: studentUserId,
        newValue: {
          classSectionId,
          sectionCode: section.sectionCode,
          studentUserId,
          unexcusedAbsenceRate: snapshot.unexcusedAbsenceRate,
          absenceThresholdPercent: snapshot.absenceThresholdPercent,
          recipients: alertPayload.recipients,
        },
        scopeType: "ClassSection",
        scopeId: classSectionId,
        correlationId: options.correlationId ?? null,
      });

      await client.query("COMMIT");
      return { alertEmitted: true, alertEventId: persistedAlertId, snapshot };
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  async function evaluateAbsenceThresholdsForSection(
    classSectionId: string,
    options: { correlationId?: string | null; actorUserId?: string | null } = {},
  ): Promise<void> {
    if (!isNotificationModuleEnabled()) {
      return;
    }

    const studentIds = await listEnrolledStudentIds(classSectionId);
    for (const studentUserId of studentIds) {
      await evaluateAbsenceThreshold(classSectionId, studentUserId, options);
    }
  }

  async function evaluateAbsenceThresholdBatch(classSectionId: string): Promise<void> {
    await evaluateAbsenceThresholdsForSection(classSectionId);
  }

  async function isStudentAtRisk(
    classSectionId: string,
    studentUserId: string,
  ): Promise<{
    atRisk: boolean;
    unexcusedAbsenceRate: number | null;
    absenceThresholdPercent: number | null;
  }> {
    if (!isNotificationModuleEnabled()) {
      return { atRisk: false, unexcusedAbsenceRate: null, absenceThresholdPercent: null };
    }

    const snapshot = await computeAbsenceSnapshot(classSectionId, studentUserId);
    if (!snapshot) {
      return { atRisk: false, unexcusedAbsenceRate: null, absenceThresholdPercent: null };
    }

    const atRisk = exceedsAbsenceThreshold(
      snapshot.unexcusedAbsenceRate,
      snapshot.absenceThresholdPercent,
    );

    return {
      atRisk,
      unexcusedAbsenceRate: snapshot.unexcusedAbsenceRate,
      absenceThresholdPercent: snapshot.absenceThresholdPercent,
    };
  }

  async function listAbsenceThresholdAlerts(filters: {
    classSectionId?: string;
    studentUserId?: string;
    allowedSectionIds: string[] | null;
    selfUserId?: string;
  }): Promise<AbsenceThresholdAlertRow[]> {
    const conditions: string[] = ["pae.alert_type = 'AbsenceThreshold'"];
    const params: unknown[] = [];

    if (filters.studentUserId) {
      params.push(filters.studentUserId);
      conditions.push(`pae.student_user_id = $${params.length}`);
    }

    if (filters.classSectionId) {
      params.push(filters.classSectionId);
      conditions.push(`pae.class_section_id = $${params.length}`);
    }

    if (filters.selfUserId) {
      params.push(filters.selfUserId);
      conditions.push(`pae.student_user_id = $${params.length}`);
    }

    if (filters.allowedSectionIds) {
      params.push(filters.allowedSectionIds);
      conditions.push(`pae.class_section_id = ANY($${params.length}::uuid[])`);
    }

    const result = await pool.query<{
      alert_event_id: string;
      class_section_id: string;
      section_code: string;
      student_user_id: string;
      student_code: string;
      display_name: string;
      unexcused_absence_rate: string;
      absence_threshold_percent: string;
      created_at: Date;
    }>(
      `
      SELECT
        pae.id AS alert_event_id,
        pae.class_section_id,
        cs.section_code,
        pae.student_user_id,
        sp.student_code,
        u.display_name,
        pae.unexcused_absence_rate,
        pae.absence_threshold_percent,
        pae.created_at
      FROM policy_alert_events pae
      JOIN class_sections cs ON cs.id = pae.class_section_id
      JOIN users u ON u.id = pae.student_user_id
      JOIN student_profiles sp ON sp.user_id = pae.student_user_id
      WHERE ${conditions.join(" AND ")}
      ORDER BY pae.created_at DESC
      `,
      params,
    );

    return result.rows.map((row) => ({
      alertEventId: row.alert_event_id,
      classSectionId: row.class_section_id,
      sectionCode: row.section_code,
      studentUserId: row.student_user_id,
      studentCode: row.student_code,
      displayName: row.display_name,
      unexcusedAbsenceRate: Number(row.unexcused_absence_rate),
      absenceThresholdPercent: Number(row.absence_threshold_percent),
      createdAt: row.created_at.toISOString(),
    }));
  }

  return {
    evaluateAbsenceThreshold,
    evaluateAbsenceThresholdsForSection,
    evaluateAbsenceThresholdBatch,
    computeAbsenceSnapshot,
    isStudentAtRisk,
    listAbsenceThresholdAlerts,
    loadClosedAttendanceStatuses,
    pool,
  };
}

export type NotificationRepository = ReturnType<typeof createNotificationRepository>;
