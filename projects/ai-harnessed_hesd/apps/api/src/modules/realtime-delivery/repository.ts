import { randomUUID } from "node:crypto";
import type pg from "pg";
import type { AttendanceStatus, SessionRoster } from "../attendance-ledger/types.js";
import { realtimeDeliveryGateway } from "./event-gateway.js";
import type {
  CheckInAttemptTelemetry,
  OperationalTelemetryEvent,
  QrTokenIssuedTelemetry,
  RealtimeRosterEvent,
  RosterUpdateReason,
  SessionLifecycleTelemetry,
} from "./types.js";

export function createRealtimeDeliveryRepository(pool: pg.Pool) {
  async function getSessionRoster(sessionId: string): Promise<SessionRoster | null> {
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

    const counts: SessionRoster["counts"] = {
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
  }

  return {
    async getRosterSnapshot(sessionId: string) {
      return getSessionRoster(sessionId);
    },

    async publishRosterUpdate(params: {
      classSessionId: string;
      reason: RosterUpdateReason;
      correlationId?: string | null;
    }): Promise<RealtimeRosterEvent | null> {
      const roster = await getSessionRoster(params.classSessionId);
      if (!roster) return null;
      return realtimeDeliveryGateway.publishRosterUpdate({
        classSessionId: params.classSessionId,
        reason: params.reason,
        correlationId: params.correlationId ?? null,
        roster,
      });
    },
  };
}

export function recordQrTokenIssuedTelemetry(params: {
  classSessionId: string;
  tokenId?: string | null;
  issuedAt: string;
  expiresAt: string;
  ttlMs: number;
  success?: boolean;
  correlationId?: string | null;
}): QrTokenIssuedTelemetry {
  const event: QrTokenIssuedTelemetry = {
    eventId: randomUUID(),
    type: "QrTokenIssued",
    classSessionId: params.classSessionId,
    tokenId: params.tokenId ?? null,
    issuedAt: params.issuedAt,
    expiresAt: params.expiresAt,
    ttlMs: params.ttlMs,
    success: params.success ?? true,
    correlationId: params.correlationId ?? null,
  };
  realtimeDeliveryGateway.publishTelemetry(event);
  return event;
}

export function recordCheckInAttemptTelemetry(params: {
  classSessionId: string;
  studentUserId: string;
  outcome: string;
  correlationId?: string | null;
}): CheckInAttemptTelemetry {
  const event: CheckInAttemptTelemetry = {
    eventId: randomUUID(),
    type: "CheckInAttemptRecorded",
    classSessionId: params.classSessionId,
    studentUserId: params.studentUserId,
    outcome: params.outcome,
    success: params.outcome === "Success",
    occurredAt: new Date().toISOString(),
    correlationId: params.correlationId ?? null,
  };
  realtimeDeliveryGateway.publishTelemetry(event);
  return event;
}

export function recordSessionLifecycleTelemetry(params: {
  type: "SessionOpened" | "SessionClosed";
  classSessionId: string;
  actorUserId: string;
  beforeState: string;
  afterState: string;
  correlationId?: string | null;
  initialRosterCount?: number;
}): SessionLifecycleTelemetry {
  const event: SessionLifecycleTelemetry = {
    eventId: randomUUID(),
    type: params.type,
    classSessionId: params.classSessionId,
    actorUserId: params.actorUserId,
    beforeState: params.beforeState,
    afterState: params.afterState,
    occurredAt: new Date().toISOString(),
    correlationId: params.correlationId ?? null,
    ...(params.initialRosterCount !== undefined ? { initialRosterCount: params.initialRosterCount } : {}),
  };
  realtimeDeliveryGateway.publishTelemetry(event);
  return event;
}

export function getOperationalTelemetrySnapshot(filter?: {
  classSessionId?: string;
  type?: OperationalTelemetryEvent["type"];
}): OperationalTelemetryEvent[] {
  return realtimeDeliveryGateway.telemetrySnapshot(filter);
}

export type RealtimeDeliveryRepository = ReturnType<typeof createRealtimeDeliveryRepository>;
