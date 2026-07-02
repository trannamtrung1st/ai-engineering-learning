import { randomUUID } from "node:crypto";
import type pg from "pg";
import type { ActorContext } from "../identity/types.js";
import { isStudentEnrolled } from "../academic-structure/validation.js";
import {
  writeAttendanceAuditEvent,
} from "../audit-and-compliance/service.js";
import { createPolicyEngineRepository } from "../policy-engine/repository.js";
import { INSTITUTION_POLICY_DEFAULTS } from "../policy-engine/defaults.js";
import {
  resolveCheckInMethodForCorrection,
  validateCorrectionPayload,
  validateCorrectionWindow,
  isAdminOverrideRole,
} from "./validation.js";
import type {
  AttendanceStatus,
  CorrectionResult,
  EffectivePolicy,
  SessionRoster,
} from "./types.js";

const DEFAULT_POLICY: EffectivePolicy = {
  manualEditWindowHours: INSTITUTION_POLICY_DEFAULTS.manualEditWindowHours,
  reasonRequired: true,
};

type CorrectionCache = CorrectionResult;

export type CorrectionCommandError =
  | { code: "SessionNotFound" }
  | { code: "StudentNotFound" }
  | { code: "NotEnrolled" }
  | { code: "InvalidPayload" }
  | { code: "ReasonRequired" }
  | { code: "EditWindowExpired" };

export function createAttendanceLedgerRepository(pool: pg.Pool) {
  const idempotencyCache = new Map<string, CorrectionCache>();
  const policyEngine = createPolicyEngineRepository(pool);

  async function loadEffectivePolicy(
    client: pg.PoolClient,
    classSectionId: string,
  ): Promise<EffectivePolicy> {
    const values = await policyEngine.resolveEffectivePolicyValues(classSectionId, new Date(), client);
    if (!values) return DEFAULT_POLICY;
    return {
      manualEditWindowHours: values.manualEditWindowHours,
      reasonRequired: true,
    };
  }

  async function writeAttendanceAudit(
    client: pg.PoolClient,
    params: {
      actorUserId: string | null;
      actor?: ActorContext | null;
      attendanceRecordId: string;
      studentUserId: string;
      classSessionId: string;
      classSectionId: string;
      oldStatus: AttendanceStatus | null;
      newStatus: AttendanceStatus;
      reason: string;
      correlationId?: string | null;
    },
  ): Promise<void> {
    const subtype =
      params.actorUserId === null
        ? "status_finalization"
        : params.actor && isAdminOverrideRole(params.actor)
          ? "admin_override"
          : "manual_update";
    const actorRole =
      params.actor?.roles[0] ?? (params.actorUserId === null ? "System" : null);

    await writeAttendanceAuditEvent(client, {
      actorUserId: params.actorUserId,
      attendanceRecordId: params.attendanceRecordId,
      oldStatus: params.oldStatus,
      newStatus: params.newStatus,
      reason: params.reason,
      studentUserId: params.studentUserId,
      classSessionId: params.classSessionId,
      classSectionId: params.classSectionId,
      actorRole,
      subtype,
      correlationId: params.correlationId,
    });
  }

  return {
    async finalizeAbsentStudents(
      client: pg.PoolClient,
      session: { id: string; classSectionId: string },
      actorUserId: string,
      options: { correlationId?: string | null } = {},
    ): Promise<void> {
      const pendingRows = await client.query<{
        id: string;
        student_user_id: string;
      }>(
        `
        SELECT id, student_user_id
        FROM attendance_records
        WHERE class_session_id = $1
          AND status = 'Pending'
        `,
        [session.id],
      );

      await client.query(
        `
        UPDATE attendance_records
        SET status = 'Absent', last_modified_by_user_id = $2, last_modified_at = now()
        WHERE class_session_id = $1
          AND status = 'Pending'
        `,
        [session.id, actorUserId],
      );

      const absentReason = "Session close absent finalization (BR-13)";
      for (const row of pendingRows.rows) {
        await writeAttendanceAudit(client, {
          actorUserId: null,
          attendanceRecordId: row.id,
          studentUserId: row.student_user_id,
          classSessionId: session.id,
          classSectionId: session.classSectionId,
          oldStatus: "Pending",
          newStatus: "Absent",
          reason: absentReason,
          correlationId: options.correlationId,
        });
      }

      const insertedRows = await client.query<{
        id: string;
        student_user_id: string;
      }>(
        `
        INSERT INTO attendance_records (
          id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
        )
        SELECT
          gen_random_uuid(),
          $1,
          $2,
          e.student_user_id,
          'Absent',
          $3
        FROM enrollments e
        WHERE e.class_section_id = $2
          AND e.status = 'Active'
          AND NOT EXISTS (
            SELECT 1
            FROM attendance_records ar
            WHERE ar.class_session_id = $1
              AND ar.student_user_id = e.student_user_id
          )
        ON CONFLICT (class_session_id, student_user_id) DO NOTHING
        RETURNING id, student_user_id
        `,
        [session.id, session.classSectionId, actorUserId],
      );

      for (const row of insertedRows.rows) {
        await writeAttendanceAudit(client, {
          actorUserId: null,
          attendanceRecordId: row.id,
          studentUserId: row.student_user_id,
          classSessionId: session.id,
          classSectionId: session.classSectionId,
          oldStatus: null,
          newStatus: "Absent",
          reason: absentReason,
          correlationId: options.correlationId,
        });
      }
    },

    async recordCheckInSuccess(
      client: pg.PoolClient,
      params: {
        classSessionId: string;
        classSectionId: string;
        studentUserId: string;
        status: "Present" | "Late";
        checkInAt: Date;
        sourceAttemptId: string;
        correlationId?: string | null;
      },
    ): Promise<string> {
      const existing = await client.query<{ id: string; status: AttendanceStatus }>(
        `
        SELECT id, status
        FROM attendance_records
        WHERE class_session_id = $1 AND student_user_id = $2
        `,
        [params.classSessionId, params.studentUserId],
      );

      const auditReason = "QR check-in success";
      let recordId: string;
      let previousStatus: AttendanceStatus | null;
      let checkInAt: Date;

      if (existing.rows[0]) {
        recordId = existing.rows[0].id;
        previousStatus = existing.rows[0].status;
        const updateResult = await client.query<{ check_in_at: Date }>(
          `
          UPDATE attendance_records
          SET
            status = $2,
            check_in_method = 'QR',
            check_in_at = $3,
            last_modified_at = $3,
            last_modified_by_user_id = $4,
            source_attempt_id = $5
          WHERE id = $1
          RETURNING check_in_at
          `,
          [
            recordId,
            params.status,
            params.checkInAt.toISOString(),
            params.studentUserId,
            params.sourceAttemptId,
          ],
        );
        checkInAt = updateResult.rows[0]!.check_in_at;
      } else {
        recordId = randomUUID();
        previousStatus = null;
        const insertResult = await client.query<{ check_in_at: Date }>(
          `
          INSERT INTO attendance_records (
            id, class_session_id, class_section_id, student_user_id, status,
            check_in_method, check_in_at, last_modified_by_user_id, source_attempt_id
          )
          VALUES ($1, $2, $3, $4, $5, 'QR', $6, $4, $7)
          RETURNING check_in_at
          `,
          [
            recordId,
            params.classSessionId,
            params.classSectionId,
            params.studentUserId,
            params.status,
            params.checkInAt.toISOString(),
            params.sourceAttemptId,
          ],
        );
        checkInAt = insertResult.rows[0]!.check_in_at;
      }

      await writeAttendanceAudit(client, {
        actorUserId: params.studentUserId,
        attendanceRecordId: recordId,
        studentUserId: params.studentUserId,
        classSessionId: params.classSessionId,
        classSectionId: params.classSectionId,
        oldStatus: previousStatus,
        newStatus: params.status,
        reason: auditReason,
        correlationId: params.correlationId ?? params.sourceAttemptId,
      });

      return checkInAt.toISOString();
    },

    async getSessionRoster(sessionId: string): Promise<SessionRoster | null> {
      const sessionResult = await pool.query<{
        id: string;
        class_section_id: string;
        state: string;
      }>(
        `
        SELECT id, class_section_id, state
        FROM class_sessions
        WHERE id = $1
        `,
        [sessionId],
      );
      const session = sessionResult.rows[0];
      if (!session) return null;

      const rowsResult = await pool.query<{
        student_user_id: string;
        student_code: string;
        display_name: string;
        status: string | null;
        check_in_method: string | null;
        check_in_at: Date | null;
        latest_attempt_outcome: string | null;
      }>(
        `
        SELECT
          u.id AS student_user_id,
          sp.student_code,
          u.display_name,
          ar.status,
          ar.check_in_method,
          ar.check_in_at,
          (
            SELECT cia.outcome
            FROM check_in_attempts cia
            WHERE cia.class_session_id = $1
              AND cia.student_user_id = u.id
            ORDER BY cia.submitted_at DESC
            LIMIT 1
          ) AS latest_attempt_outcome
        FROM enrollments e
        JOIN users u ON u.id = e.student_user_id
        JOIN student_profiles sp ON sp.user_id = u.id
        LEFT JOIN attendance_records ar
          ON ar.class_session_id = $1
          AND ar.student_user_id = e.student_user_id
        WHERE e.class_section_id = $2
          AND e.status = 'Active'
        ORDER BY sp.student_code
        `,
        [sessionId, session.class_section_id],
      );

      const rejectedResult = await pool.query<{ count: string }>(
        `
        SELECT COUNT(*)::text AS count
        FROM check_in_attempts
        WHERE class_session_id = $1
          AND outcome <> 'Success'
        `,
        [sessionId],
      );

      const counts = {
        present: 0,
        late: 0,
        pending: 0,
        absent: 0,
        excused: 0,
        manualPresent: 0,
        rejectedAttempts: Number.parseInt(rejectedResult.rows[0]?.count ?? "0", 10),
      };

      const rows = rowsResult.rows.map((row) => {
        const attendanceStatus = (row.status ?? "Pending") as AttendanceStatus;
        if (attendanceStatus === "Present") counts.present += 1;
        else if (attendanceStatus === "Late") counts.late += 1;
        else if (attendanceStatus === "Pending") counts.pending += 1;
        else if (attendanceStatus === "Absent") counts.absent += 1;
        else if (attendanceStatus === "Excused") counts.excused += 1;
        else if (attendanceStatus === "Manual Present") counts.manualPresent += 1;

        return {
          studentUserId: row.student_user_id,
          studentCode: row.student_code,
          displayName: row.display_name,
          attendanceStatus,
          checkInMethod: row.check_in_method as SessionRoster["rows"][number]["checkInMethod"],
          checkInAt: row.check_in_at?.toISOString() ?? null,
          latestAttemptOutcome: row.latest_attempt_outcome,
        };
      });

      return {
        classSessionId: session.id,
        state: session.state,
        counts,
        rows,
      };
    },

    async correctAttendance(params: {
      sessionId: string;
      studentUserId: string;
      actor: ActorContext;
      body: { status?: unknown; reason?: unknown };
      idempotencyKey?: string;
      correlationId?: string | null;
    }): Promise<
      | { ok: true; result: CorrectionResult }
      | { ok: false; error: CorrectionCommandError }
    > {
      const cacheKey = params.idempotencyKey
        ? `correct:${params.sessionId}:${params.studentUserId}:${params.actor.userId}:${params.idempotencyKey}`
        : null;

      if (cacheKey) {
        const cached = idempotencyCache.get(cacheKey);
        if (cached) {
          return { ok: true, result: cached };
        }
      }

      const payload = validateCorrectionPayload(params.body);
      if (!payload.ok) {
        return {
          ok: false,
          error: { code: payload.error.code },
        };
      }

      const client = await pool.connect();
      try {
        await client.query("BEGIN");

        const sessionResult = await client.query<{
          id: string;
          class_section_id: string;
          state: string;
          closed_at: Date | null;
        }>(
          `
          SELECT id, class_section_id, state, closed_at
          FROM class_sessions
          WHERE id = $1
          FOR UPDATE
          `,
          [params.sessionId],
        );
        const session = sessionResult.rows[0];
        if (!session) {
          await client.query("ROLLBACK");
          return { ok: false, error: { code: "SessionNotFound" } };
        }

        const enrolled = await isStudentEnrolled(
          client.query.bind(client),
          params.studentUserId,
          session.class_section_id,
        );
        if (!enrolled) {
          await client.query("ROLLBACK");
          return { ok: false, error: { code: "NotEnrolled" } };
        }

        const policy = await loadEffectivePolicy(client, session.class_section_id);
        const windowCheck = validateCorrectionWindow({
          actor: params.actor,
          sessionState: session.state,
          closedAt: session.closed_at?.toISOString() ?? null,
          policy,
        });
        if (!windowCheck.ok) {
          await client.query("ROLLBACK");
          return { ok: false, error: { code: windowCheck.error.code } };
        }

        const existing = await client.query<{
          id: string;
          status: AttendanceStatus;
          check_in_at: Date | null;
        }>(
          `
          SELECT id, status, check_in_at
          FROM attendance_records
          WHERE class_session_id = $1 AND student_user_id = $2
          FOR UPDATE
          `,
          [params.sessionId, params.studentUserId],
        );

        const previousStatus = (existing.rows[0]?.status ?? "Pending") as AttendanceStatus;
        const checkInMethod = resolveCheckInMethodForCorrection(params.actor);
        const now = new Date();
        let recordId: string;
        let checkInAt: string | null;

        if (existing.rows[0]) {
          recordId = existing.rows[0].id;
          const updateResult = await client.query<{ check_in_at: Date | null }>(
            `
            UPDATE attendance_records
            SET
              status = $2,
              check_in_method = $3,
              check_in_at = COALESCE(check_in_at, $4),
              last_modified_at = $4,
              last_modified_by_user_id = $5,
              modification_reason = $6
            WHERE id = $1
            RETURNING check_in_at
            `,
            [
              recordId,
              payload.status,
              checkInMethod,
              now.toISOString(),
              params.actor.userId,
              payload.reason,
            ],
          );
          checkInAt = updateResult.rows[0]?.check_in_at?.toISOString() ?? null;
        } else {
          recordId = randomUUID();
          const insertResult = await client.query<{ check_in_at: Date }>(
            `
            INSERT INTO attendance_records (
              id, class_session_id, class_section_id, student_user_id, status,
              check_in_method, check_in_at, last_modified_by_user_id, modification_reason
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING check_in_at
            `,
            [
              recordId,
              params.sessionId,
              session.class_section_id,
              params.studentUserId,
              payload.status,
              checkInMethod,
              now.toISOString(),
              params.actor.userId,
              payload.reason,
            ],
          );
          checkInAt = insertResult.rows[0]!.check_in_at.toISOString();
        }

        await writeAttendanceAudit(client, {
          actorUserId: params.actor.userId,
          actor: params.actor,
          attendanceRecordId: recordId,
          studentUserId: params.studentUserId,
          classSessionId: params.sessionId,
          classSectionId: session.class_section_id,
          oldStatus: existing.rows[0] ? previousStatus : null,
          newStatus: payload.status,
          reason: payload.reason,
          correlationId: params.correlationId,
        });

        const result: CorrectionResult = {
          classSessionId: params.sessionId,
          studentUserId: params.studentUserId,
          attendanceStatus: payload.status,
          checkInMethod,
          checkInAt,
          previousStatus: existing.rows[0] ? previousStatus : null,
          reason: payload.reason,
        };

        if (cacheKey) {
          idempotencyCache.set(cacheKey, result);
        }

        await client.query("COMMIT");
        return { ok: true, result };
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      } finally {
        client.release();
      }
    },

    /** Test helper — reset in-process idempotency cache between cases. */
    clearIdempotencyCache(): void {
      idempotencyCache.clear();
    },
  };
}

export type AttendanceLedgerRepository = ReturnType<typeof createAttendanceLedgerRepository>;
