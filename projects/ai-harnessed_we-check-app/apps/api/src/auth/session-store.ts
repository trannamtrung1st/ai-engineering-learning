import { randomUUID } from "node:crypto";
import type { UserRole } from "@wecheck/domain";
import type { DbPool } from "../infra/db.js";
import { now } from "../infra/clock.js";
import type { AuthSession, AuthUser } from "./types.js";
import {
  computeExpiresAt,
  isSessionExpired,
  parseInactivityHours,
  POLICY_KEY_SESSION_INACTIVITY,
} from "./session-policy.js";

interface SessionRow {
  id: string;
  user_id: string;
  expires_at: Date;
  last_activity_at: Date;
  revoked_at: Date | null;
  institutional_id: string;
  display_name: string;
  email: string;
  role: UserRole;
  active: boolean;
}

function mapRow(row: SessionRow): { session: AuthSession; user: AuthUser } {
  return {
    session: {
      id: row.id,
      userId: row.user_id,
      expiresAt: row.expires_at,
      lastActivityAt: row.last_activity_at,
    },
    user: {
      id: row.user_id,
      institutionalId: row.institutional_id,
      displayName: row.display_name,
      email: row.email,
      role: row.role,
      active: row.active,
    },
  };
}

export class SessionStore {
  constructor(private readonly db: DbPool) {}

  async getInactivityHours(): Promise<number> {
    const result = await this.db.query<{ value: string }>(
      "SELECT value FROM policy_settings WHERE key = $1",
      [POLICY_KEY_SESSION_INACTIVITY],
    );
    const raw = result.rows[0]?.value;
    return raw ? parseInactivityHours(raw) : 8;
  }

  async resolveSession(sessionId: string): Promise<
    | { ok: true; session: AuthSession; user: AuthUser }
    | { ok: false; reason: "missing" | "revoked" | "expired" | "inactive_user" }
  > {
    const result = await this.db.query<SessionRow>(
      `SELECT s.id, s.user_id, s.expires_at, s.last_activity_at, s.revoked_at,
              u.institutional_id, u.display_name, u.email, u.role, u.active
       FROM auth_sessions s
       INNER JOIN users u ON u.id = s.user_id
       WHERE s.id = $1`,
      [sessionId],
    );

    const row = result.rows[0];
    if (!row) {
      return { ok: false, reason: "missing" };
    }
    if (row.revoked_at) {
      return { ok: false, reason: "revoked" };
    }
    if (!row.active) {
      return { ok: false, reason: "inactive_user" };
    }

    const inactivityHours = await this.getInactivityHours();
    if (isSessionExpired(row.last_activity_at, inactivityHours, now())) {
      return { ok: false, reason: "expired" };
    }

    return { ok: true, ...mapRow(row) };
  }

  async touchSession(sessionId: string): Promise<void> {
    const at = now();
    const inactivityHours = await this.getInactivityHours();
    const expiresAt = computeExpiresAt(at, inactivityHours);
    await this.db.query(
      `UPDATE auth_sessions
       SET last_activity_at = $2, expires_at = $3
       WHERE id = $1 AND revoked_at IS NULL`,
      [sessionId, at, expiresAt],
    );
  }

  async createSession(userId: string): Promise<AuthSession> {
    const at = now();
    const inactivityHours = await this.getInactivityHours();
    const expiresAt = computeExpiresAt(at, inactivityHours);
    const id = randomUUID();
    await this.db.query(
      `INSERT INTO auth_sessions (id, user_id, expires_at, last_activity_at)
       VALUES ($1, $2, $3, $4)`,
      [id, userId, expiresAt, at],
    );
    return { id, userId, expiresAt, lastActivityAt: at };
  }

  async revokeSession(sessionId: string): Promise<void> {
    await this.db.query(
      "UPDATE auth_sessions SET revoked_at = $2 WHERE id = $1",
      [sessionId, now()],
    );
  }

  async revokeAllSessionsForUser(userId: string): Promise<void> {
    await this.db.query(
      `UPDATE auth_sessions SET revoked_at = $2
       WHERE user_id = $1 AND revoked_at IS NULL`,
      [userId, now()],
    );
  }
}

export interface TestUserInput {
  institutionalId: string;
  displayName: string;
  email: string;
  role: UserRole;
  active?: boolean;
}

export async function createTestUser(
  db: DbPool,
  input: TestUserInput,
): Promise<string> {
  const id = randomUUID();
  await db.query(
    `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
     VALUES ($1, $2, $3, $4, '', $5, $6)`,
    [
      id,
      input.institutionalId,
      input.displayName,
      input.email,
      input.role,
      input.active ?? true,
    ],
  );
  return id;
}

export async function truncateAuthTables(db: DbPool): Promise<void> {
  await db.query(
    "TRUNCATE check_in_attempts, security_audit_logs RESTART IDENTITY CASCADE",
  );
  await db.query(
    "TRUNCATE attendance_audit_logs, qr_tokens, attendance_records, sessions RESTART IDENTITY CASCADE",
  );
  await db.query(`
    TRUNCATE TABLE
      roster_import_batches,
      enrollments,
      class_assignments,
      classes,
      subjects
    RESTART IDENTITY CASCADE
  `);
  await db.query("DELETE FROM user_audit_logs");
  await db.query("DELETE FROM auth_sessions");
  await db.query(
    "UPDATE policy_settings SET updated_by_id = NULL WHERE updated_by_id IS NOT NULL",
  );
  await db.query("TRUNCATE notifications RESTART IDENTITY CASCADE");
  await db.query("TRUNCATE export_audit_logs RESTART IDENTITY CASCADE");
  await db.query("DELETE FROM class_assignments");
  await db.query("DELETE FROM users");
  await db.query("DELETE FROM policy_settings WHERE key = 'preview_seed_version'");
  await db.query(
    `UPDATE policy_settings SET value = '8', updated_by_id = NULL
     WHERE key = 'session_inactivity_hours'`,
  );
}
