import { NotificationType } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { now } from "../../infra/clock.js";
import {
  DEFAULT_ABSENCE_THRESHOLD_PERCENT,
  type AbsenceRateInput,
} from "./absence-threshold.js";
import type { AbsenceThresholdPayload } from "./types.js";
import { encodeNotificationCursor } from "./validation.js";

export const POLICY_KEY_ABSENCE_THRESHOLD = "absence_threshold_percent";
export const POLICY_KEY_ABSENCE_AUTO_WARNING = "absence_auto_warning_enabled";
const DEFAULT_ABSENCE_AUTO_WARNING_ENABLED = false;

export class PolicyRepository {
  constructor(private readonly db: DbPool) {}

  async getAbsenceThresholdPercent(): Promise<number> {
    const result = await this.db.query<{ value: string }>(
      "SELECT value FROM policy_settings WHERE key = $1",
      [POLICY_KEY_ABSENCE_THRESHOLD],
    );
    const raw = result.rows[0]?.value;
    if (!raw) {
      return DEFAULT_ABSENCE_THRESHOLD_PERCENT;
    }
    const parsed = Number.parseInt(raw, 10);
    if (Number.isNaN(parsed) || parsed < 1 || parsed > 100) {
      return DEFAULT_ABSENCE_THRESHOLD_PERCENT;
    }
    return parsed;
  }

  async setAbsenceThresholdPercent(
    thresholdPercent: number,
    adminId: string,
  ): Promise<number> {
    await this.db.query(
      `INSERT INTO policy_settings (key, value, updated_by_id, updated_at)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (key) DO UPDATE
       SET value = EXCLUDED.value,
           updated_by_id = EXCLUDED.updated_by_id,
           updated_at = EXCLUDED.updated_at`,
      [POLICY_KEY_ABSENCE_THRESHOLD, String(thresholdPercent), adminId, now()],
    );
    return thresholdPercent;
  }

  async getAbsenceAutoWarningEnabled(): Promise<boolean> {
    const result = await this.db.query<{ value: string }>(
      "SELECT value FROM policy_settings WHERE key = $1",
      [POLICY_KEY_ABSENCE_AUTO_WARNING],
    );
    const raw = result.rows[0]?.value;
    if (!raw) {
      return DEFAULT_ABSENCE_AUTO_WARNING_ENABLED;
    }
    return raw === "true" || raw === "1";
  }

  async setAbsenceAutoWarningEnabled(
    enabled: boolean,
    adminId: string,
  ): Promise<boolean> {
    await this.db.query(
      `INSERT INTO policy_settings (key, value, updated_by_id, updated_at)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (key) DO UPDATE
       SET value = EXCLUDED.value,
           updated_by_id = EXCLUDED.updated_by_id,
           updated_at = EXCLUDED.updated_at`,
      [
        POLICY_KEY_ABSENCE_AUTO_WARNING,
        enabled ? "true" : "false",
        adminId,
        now(),
      ],
    );
    return enabled;
  }
}

interface NotificationRow {
  id: string;
  user_id: string;
  type: NotificationType;
  payload: AbsenceThresholdPayload;
  read_at: Date | null;
  created_at: Date;
}

export class NotificationRepository {
  constructor(private readonly db: DbPool) {}

  async listForUser(
    userId: string,
    limit: number,
    cursor?: { createdAt: string; id: string },
  ): Promise<{ items: NotificationRow[]; hasMore: boolean }> {
    const values: unknown[] = [userId];
    let cursorClause = "";

    if (cursor) {
      values.push(cursor.createdAt, cursor.id);
      cursorClause = `AND (n.created_at, n.id) < ($2::timestamptz, $3::uuid)`;
    }

    values.push(limit + 1);
    const limitParam = values.length;

    const result = await this.db.query<NotificationRow>(
      `SELECT n.id, n.user_id, n.type, n.payload, n.read_at, n.created_at
       FROM notifications n
       WHERE n.user_id = $1
       ${cursorClause}
       ORDER BY n.created_at DESC, n.id DESC
       LIMIT $${limitParam}`,
      values,
    );

    const hasMore = result.rows.length > limit;
    const items = hasMore ? result.rows.slice(0, limit) : result.rows;
    return { items, hasMore };
  }

  async countForUser(userId: string): Promise<number> {
    const result = await this.db.query<{ count: string }>(
      "SELECT COUNT(*)::text AS count FROM notifications WHERE user_id = $1",
      [userId],
    );
    return Number.parseInt(result.rows[0]?.count ?? "0", 10);
  }

  async findById(notificationId: string): Promise<NotificationRow | null> {
    const result = await this.db.query<NotificationRow>(
      `SELECT id, user_id, type, payload, read_at, created_at
       FROM notifications WHERE id = $1`,
      [notificationId],
    );
    return result.rows[0] ?? null;
  }

  async markRead(notificationId: string, userId: string): Promise<boolean> {
    const result = await this.db.query(
      `UPDATE notifications
       SET read_at = COALESCE(read_at, NOW())
       WHERE id = $1 AND user_id = $2`,
      [notificationId, userId],
    );
    return (result.rowCount ?? 0) > 0;
  }

  async createAbsenceWarning(
    userId: string,
    payload: AbsenceThresholdPayload,
  ): Promise<string | null> {
    const result = await this.db.query<{ id: string }>(
      `INSERT INTO notifications (user_id, type, payload)
       VALUES ($1, $2, $3::jsonb)
       ON CONFLICT DO NOTHING
       RETURNING id`,
      [userId, NotificationType.AbsenceThresholdWarning, JSON.stringify(payload)],
    );
    return result.rows[0]?.id ?? null;
  }

  async getStudentAbsenceStats(
    studentId: string,
    classId: string,
    subjectId: string,
  ): Promise<AbsenceRateInput> {
    const result = await this.db.query<{
      unexcused: string;
      total: string;
    }>(
      `SELECT
         COUNT(*) FILTER (WHERE ar.status = 'Absent')::text AS unexcused,
         COUNT(*) FILTER (
           WHERE ar.status IN ('Present', 'Absent', 'Excused', 'Rejected')
         )::text AS total
       FROM attendance_records ar
       JOIN sessions s ON s.id = ar.session_id
       WHERE ar.student_id = $1
         AND s.class_id = $2
         AND s.subject_id = $3
         AND s.status = 'Closed'`,
      [studentId, classId, subjectId],
    );
    return {
      unexcusedAbsenceCount: Number.parseInt(result.rows[0]?.unexcused ?? "0", 10),
      sessionCount: Number.parseInt(result.rows[0]?.total ?? "0", 10),
    };
  }

  async listStudentsInSession(
    sessionId: string,
  ): Promise<Array<{ studentId: string; displayName: string }>> {
    const result = await this.db.query<{
      student_id: string;
      display_name: string;
    }>(
      `SELECT u.id AS student_id, u.display_name
       FROM attendance_records ar
       JOIN users u ON u.id = ar.student_id
       WHERE ar.session_id = $1`,
      [sessionId],
    );
    return result.rows.map((row) => ({
      studentId: row.student_id,
      displayName: row.display_name,
    }));
  }

  async findSessionContext(
    sessionId: string,
  ): Promise<{
    classId: string;
    subjectId: string;
    status: string;
  } | null> {
    const result = await this.db.query<{
      class_id: string;
      subject_id: string;
      status: string;
    }>(
      "SELECT class_id, subject_id, status FROM sessions WHERE id = $1",
      [sessionId],
    );
    const row = result.rows[0];
    if (!row) {
      return null;
    }
    return {
      classId: row.class_id,
      subjectId: row.subject_id,
      status: row.status,
    };
  }

  async findSubject(
    subjectId: string,
  ): Promise<{ code: string; name: string } | null> {
    const result = await this.db.query<{ code: string; name: string }>(
      "SELECT code, name FROM subjects WHERE id = $1",
      [subjectId],
    );
    return result.rows[0] ?? null;
  }

  async listAssignedInstructors(
    classId: string,
    subjectId: string,
  ): Promise<string[]> {
    const result = await this.db.query<{ instructor_id: string }>(
      `SELECT instructor_id FROM class_assignments
       WHERE class_id = $1 AND subject_id = $2`,
      [classId, subjectId],
    );
    return result.rows.map((row) => row.instructor_id);
  }
}

export function toNotificationDto(row: NotificationRow) {
  return {
    id: row.id,
    type: row.type,
    payload: row.payload,
    readAt: row.read_at?.toISOString() ?? null,
    createdAt: row.created_at.toISOString(),
  };
}

export function buildNextCursor(
  items: NotificationRow[],
  hasMore: boolean,
): string | null {
  if (!hasMore || items.length === 0) {
    return null;
  }
  const last = items[items.length - 1]!;
  return encodeNotificationCursor(last.created_at.toISOString(), last.id);
}

export async function truncateNotificationTables(db: DbPool): Promise<void> {
  await db.query("TRUNCATE notifications RESTART IDENTITY CASCADE");
}
