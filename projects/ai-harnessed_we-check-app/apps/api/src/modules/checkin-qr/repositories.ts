import { randomUUID } from "node:crypto";
import type { PoolClient } from "pg";
import type { DbPool } from "../../infra/db.js";
import type { QrTokenRow, SessionCheckInContext, SessionDisplayContext } from "./types.js";

type DbQueryable = DbPool | PoolClient;

interface QrTokenDbRow {
  id: string;
  session_id: string;
  status: string;
  issued_at: Date;
  expires_at: Date;
  consumed_by_student_id: string | null;
}

interface SessionDbRow {
  id: string;
  class_id: string;
  subject_id: string;
  status: string;
  opened_at: Date | null;
  closed_at: Date | null;
  scheduled_start: Date;
  room_latitude: number;
  room_longitude: number;
  gps_radius_meters: number;
}

interface SessionDisplayDbRow extends SessionDbRow {
  class_code: string;
  subject_code: string;
  room_name: string;
}

export class QrTokenRepository {
  constructor(private readonly db: DbPool) {}

  async findById(tokenId: string): Promise<QrTokenRow | null> {
    const result = await this.db.query<QrTokenDbRow>(
      `SELECT id, session_id, status, issued_at, expires_at, consumed_by_student_id
       FROM qr_tokens WHERE id = $1`,
      [tokenId],
    );
    const row = result.rows[0];
    return row ? this.toRow(row) : null;
  }

  async findByIdForUpdate(
    client: DbQueryable,
    tokenId: string,
  ): Promise<QrTokenRow | null> {
    const result = await client.query<QrTokenDbRow>(
      `SELECT id, session_id, status, issued_at, expires_at, consumed_by_student_id
       FROM qr_tokens WHERE id = $1 FOR UPDATE`,
      [tokenId],
    );
    const row = result.rows[0];
    return row ? this.toRow(row) : null;
  }

  async findSessionContext(sessionId: string): Promise<SessionCheckInContext | null> {
    const result = await this.db.query<SessionDbRow>(
      `SELECT id, class_id, subject_id, status, opened_at, closed_at, scheduled_start,
              room_latitude, room_longitude, gps_radius_meters
       FROM sessions WHERE id = $1`,
      [sessionId],
    );
    const row = result.rows[0];
    if (!row || row.room_latitude === null || row.room_longitude === null) {
      return null;
    }
    return {
      id: row.id,
      classId: row.class_id,
      subjectId: row.subject_id,
      status: row.status,
      openedAt: row.opened_at,
      closedAt: row.closed_at,
      scheduledStart: row.scheduled_start,
      roomLatitude: row.room_latitude,
      roomLongitude: row.room_longitude,
      gpsRadiusMeters: row.gps_radius_meters,
    };
  }

  async findSessionDisplayContext(
    sessionId: string,
  ): Promise<SessionDisplayContext | null> {
    const result = await this.db.query<SessionDisplayDbRow>(
      `SELECT s.id, s.class_id, s.subject_id, s.status, s.opened_at, s.closed_at,
              s.scheduled_start, s.room_latitude, s.room_longitude, s.gps_radius_meters,
              s.room_name, c.code AS class_code, sub.code AS subject_code
       FROM sessions s
       JOIN classes c ON c.id = s.class_id
       JOIN subjects sub ON sub.id = s.subject_id
       WHERE s.id = $1`,
      [sessionId],
    );
    const row = result.rows[0];
    if (!row || row.room_latitude === null || row.room_longitude === null) {
      return null;
    }
    return {
      id: row.id,
      classId: row.class_id,
      subjectId: row.subject_id,
      status: row.status,
      openedAt: row.opened_at,
      closedAt: row.closed_at,
      scheduledStart: row.scheduled_start,
      roomLatitude: row.room_latitude,
      roomLongitude: row.room_longitude,
      gpsRadiusMeters: row.gps_radius_meters,
      classCode: row.class_code,
      subjectCode: row.subject_code,
      roomName: row.room_name,
    };
  }

  async consumeToken(
    client: DbQueryable,
    tokenId: string,
    studentId: string,
    consumedAt: Date,
  ): Promise<void> {
    await client.query(
      `UPDATE qr_tokens
       SET status = 'Consumed', consumed_at = $2, consumed_by_student_id = $3
       WHERE id = $1`,
      [tokenId, consumedAt, studentId],
    );
  }

  private toRow(row: QrTokenDbRow): QrTokenRow {
    return {
      id: row.id,
      sessionId: row.session_id,
      status: row.status,
      issuedAt: row.issued_at,
      expiresAt: row.expires_at,
      consumedByStudentId: row.consumed_by_student_id,
    };
  }
}

export class CheckInAttemptRepository {
  async insert(
    client: DbQueryable,
    input: {
      sessionId: string;
      studentId: string;
      qrTokenId: string | null;
      outcome: string;
      attemptedAt: Date;
      distanceMeters?: number | null;
      spoofFlags?: Record<string, unknown> | null;
      clientUserAgent?: string | null;
    },
  ): Promise<string> {
    const id = randomUUID();
    await client.query(
      `INSERT INTO check_in_attempts
         (id, session_id, student_id, qr_token_id, outcome, attempted_at,
          distance_meters, spoof_flags, client_user_agent)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
      [
        id,
        input.sessionId,
        input.studentId,
        input.qrTokenId,
        input.outcome,
        input.attemptedAt,
        input.distanceMeters ?? null,
        input.spoofFlags ? JSON.stringify(input.spoofFlags) : null,
        input.clientUserAgent ?? null,
      ],
    );
    return id;
  }
}

export class SecurityAuditRepository {
  async insert(
    client: DbQueryable,
    input: {
      eventType: string;
      sessionId: string | null;
      qrTokenId: string | null;
      studentId: string | null;
      details: Record<string, unknown> | null;
    },
  ): Promise<void> {
    await client.query(
      `INSERT INTO security_audit_logs
         (id, event_type, session_id, qr_token_id, student_id, details)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [
        randomUUID(),
        input.eventType,
        input.sessionId,
        input.qrTokenId,
        input.studentId,
        input.details ? JSON.stringify(input.details) : null,
      ],
    );
  }
}
