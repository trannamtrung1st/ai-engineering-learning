import { createHash, randomUUID } from "node:crypto";
import type pg from "pg";
import { validateCloseTransition, validateOpenTransition } from "./validation.js";
import type {
  ClassSessionRow,
  CloseSessionResult,
  CloseSummary,
  OpenSessionResult,
  SessionState,
} from "./types.js";

const QR_TTL_MS = 30_000;

function mapSession(row: {
  id: string;
  class_section_id: string;
  room_id: string | null;
  scheduled_start_at: Date;
  scheduled_end_at: Date;
  state: SessionState;
  opened_at: Date | null;
  opened_by_user_id: string | null;
  closed_at: Date | null;
  closed_by_user_id: string | null;
}): ClassSessionRow {
  return {
    id: row.id,
    classSectionId: row.class_section_id,
    roomId: row.room_id,
    scheduledStartAt: row.scheduled_start_at.toISOString(),
    scheduledEndAt: row.scheduled_end_at.toISOString(),
    state: row.state,
    openedAt: row.opened_at?.toISOString() ?? null,
    openedByUserId: row.opened_by_user_id,
    closedAt: row.closed_at?.toISOString() ?? null,
    closedByUserId: row.closed_by_user_id,
  };
}

function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export type SessionCommandError =
  | { code: "SessionNotFound" }
  | { code: "InvalidSessionTransition"; fromState: SessionState }
  | { code: "InvalidPayload" };

export function createSessionLifecycleRepository(pool: pg.Pool) {
  const idempotencyCache = new Map<string, OpenSessionResult | CloseSessionResult>();

  async function getSessionForUpdate(
    client: pg.PoolClient,
    sessionId: string,
  ): Promise<ClassSessionRow | null> {
    const result = await client.query<{
      id: string;
      class_section_id: string;
      room_id: string | null;
      scheduled_start_at: Date;
      scheduled_end_at: Date;
      state: SessionState;
      opened_at: Date | null;
      opened_by_user_id: string | null;
      closed_at: Date | null;
      closed_by_user_id: string | null;
    }>(
      `
      SELECT
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
        state, opened_at, opened_by_user_id, closed_at, closed_by_user_id
      FROM class_sessions
      WHERE id = $1
      FOR UPDATE
      `,
      [sessionId],
    );
    const row = result.rows[0];
    return row ? mapSession(row) : null;
  }

  async function issueQrToken(
    client: pg.PoolClient,
    sessionId: string,
  ): Promise<{ expiresAt: string; qrPayload: string }> {
    const token = randomUUID();
    const tokenHash = hashToken(token);
    const issuedAt = new Date();
    const expiresAt = new Date(issuedAt.getTime() + QR_TTL_MS);

    await client.query(
      `
      UPDATE qr_session_tokens
      SET state = 'Expired'
      WHERE class_session_id = $1 AND state = 'Valid'
      `,
      [sessionId],
    );

    await client.query(
      `
      INSERT INTO qr_session_tokens (id, class_session_id, token_hash, state, issued_at, expires_at)
      VALUES ($1, $2, $3, 'Valid', $4, $5)
      `,
      [randomUUID(), sessionId, tokenHash, issuedAt.toISOString(), expiresAt.toISOString()],
    );

    return { expiresAt: expiresAt.toISOString(), qrPayload: token };
  }

  async function invalidateSessionTokens(client: pg.PoolClient, sessionId: string): Promise<void> {
    await client.query(
      `
      UPDATE qr_session_tokens
      SET state = 'Invalid'
      WHERE class_session_id = $1 AND state IN ('Valid', 'Expired')
      `,
      [sessionId],
    );
  }

  async function computeCloseSummary(
    client: pg.PoolClient,
    sessionId: string,
  ): Promise<CloseSummary> {
    const result = await client.query<{ status: string; count: string }>(
      `
      SELECT status, COUNT(*)::text AS count
      FROM attendance_records
      WHERE class_session_id = $1
      GROUP BY status
      `,
      [sessionId],
    );

    const counts: CloseSummary = {
      present: 0,
      late: 0,
      manualPresent: 0,
      absent: 0,
    };

    for (const row of result.rows) {
      const n = Number.parseInt(row.count, 10);
      if (row.status === "Present") counts.present = n;
      else if (row.status === "Late") counts.late = n;
      else if (row.status === "Manual Present") counts.manualPresent = n;
      else if (row.status === "Absent") counts.absent = n;
    }

    return counts;
  }

  async function finalizeAbsentStudents(
    client: pg.PoolClient,
    session: ClassSessionRow,
    actorUserId: string,
  ): Promise<void> {
    await client.query(
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
      `,
      [session.id, session.classSectionId, actorUserId],
    );
  }

  async function writeAuditLog(
    client: pg.PoolClient,
    params: {
      actorUserId: string;
      actionType: "SessionOpen" | "SessionClose";
      sessionId: string;
      oldValue: Record<string, unknown> | null;
      newValue: Record<string, unknown>;
      correlationId?: string;
    },
  ): Promise<void> {
    await client.query(
      `
      INSERT INTO audit_logs (
        id, actor_user_id, action_type, target_type, target_id, old_value, new_value, correlation_id
      )
      VALUES ($1, $2, $3, 'ClassSession', $4, $5, $6, $7)
      `,
      [
        randomUUID(),
        params.actorUserId,
        params.actionType,
        params.sessionId,
        params.oldValue ? JSON.stringify(params.oldValue) : null,
        JSON.stringify(params.newValue),
        params.correlationId ?? null,
      ],
    );
  }

  return {
    async getSessionState(sessionId: string): Promise<ClassSessionRow | null> {
      const result = await pool.query<{
        id: string;
        class_section_id: string;
        room_id: string | null;
        scheduled_start_at: Date;
        scheduled_end_at: Date;
        state: SessionState;
        opened_at: Date | null;
        opened_by_user_id: string | null;
        closed_at: Date | null;
        closed_by_user_id: string | null;
      }>(
        `
        SELECT
          id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
          state, opened_at, opened_by_user_id, closed_at, closed_by_user_id
        FROM class_sessions
        WHERE id = $1
        `,
        [sessionId],
      );
      const row = result.rows[0];
      return row ? mapSession(row) : null;
    },

    async openSession(
      sessionId: string,
      actorUserId: string,
      options: { roomId?: string | null; idempotencyKey?: string } = {},
    ): Promise<{ ok: true; result: OpenSessionResult } | { ok: false; error: SessionCommandError }> {
      const cacheKey =
        options.idempotencyKey
          ? `open:${sessionId}:${actorUserId}:${options.idempotencyKey}`
          : null;

      if (cacheKey) {
        const cached = idempotencyCache.get(cacheKey);
        if (cached && cached.state === "Open") {
          return { ok: true, result: cached as OpenSessionResult };
        }
      }

      const client = await pool.connect();
      try {
        await client.query("BEGIN");
        const session = await getSessionForUpdate(client, sessionId);
        if (!session) {
          await client.query("ROLLBACK");
          return { ok: false, error: { code: "SessionNotFound" } };
        }

        if (session.state === "Open") {
          if (cacheKey && idempotencyCache.has(cacheKey)) {
            const cached = idempotencyCache.get(cacheKey) as OpenSessionResult;
            await client.query("COMMIT");
            return { ok: true, result: cached };
          }
          await client.query("ROLLBACK");
          return {
            ok: false,
            error: { code: "InvalidSessionTransition", fromState: session.state },
          };
        }

        const transition = validateOpenTransition(session.state);
        if (!transition.allowed) {
          await client.query("ROLLBACK");
          return {
            ok: false,
            error: { code: "InvalidSessionTransition", fromState: transition.fromState },
          };
        }

        const openedAt = new Date();
        const roomId = options.roomId !== undefined ? options.roomId : session.roomId;

        await client.query(
          `
          UPDATE class_sessions
          SET state = 'Open', opened_at = $2, opened_by_user_id = $3, room_id = $4
          WHERE id = $1
          `,
          [sessionId, openedAt.toISOString(), actorUserId, roomId],
        );

        const qr = await issueQrToken(client, sessionId);

        await writeAuditLog(client, {
          actorUserId,
          actionType: "SessionOpen",
          sessionId,
          oldValue: { state: session.state },
          newValue: { state: "Open", openedAt: openedAt.toISOString(), openedByUserId: actorUserId },
        });

        const result: OpenSessionResult = {
          classSessionId: sessionId,
          state: "Open",
          openedAt: openedAt.toISOString(),
          qr,
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

    async closeSession(
      sessionId: string,
      actorUserId: string,
      options: { idempotencyKey?: string } = {},
    ): Promise<{ ok: true; result: CloseSessionResult } | { ok: false; error: SessionCommandError }> {
      const cacheKey =
        options.idempotencyKey
          ? `close:${sessionId}:${actorUserId}:${options.idempotencyKey}`
          : null;

      if (cacheKey) {
        const cached = idempotencyCache.get(cacheKey);
        if (cached && cached.state === "Closed") {
          return { ok: true, result: cached as CloseSessionResult };
        }
      }

      const client = await pool.connect();
      try {
        await client.query("BEGIN");
        const session = await getSessionForUpdate(client, sessionId);
        if (!session) {
          await client.query("ROLLBACK");
          return { ok: false, error: { code: "SessionNotFound" } };
        }

        const transition = validateCloseTransition(session.state);
        if (!transition.allowed) {
          await client.query("ROLLBACK");
          return {
            ok: false,
            error: { code: "InvalidSessionTransition", fromState: transition.fromState },
          };
        }

        if (transition.idempotent) {
          const summary = await computeCloseSummary(client, sessionId);
          const result: CloseSessionResult = {
            classSessionId: session.id,
            state: "Closed",
            closedAt: session.closedAt!,
            summary,
          };
          if (cacheKey) {
            idempotencyCache.set(cacheKey, result);
          }
          await client.query("COMMIT");
          return { ok: true, result };
        }

        const closedAt = new Date();

        await client.query(
          `
          UPDATE class_sessions
          SET state = 'Closed', closed_at = $2, closed_by_user_id = $3
          WHERE id = $1
          `,
          [sessionId, closedAt.toISOString(), actorUserId],
        );

        await invalidateSessionTokens(client, sessionId);
        await finalizeAbsentStudents(client, session, actorUserId);

        const summary = await computeCloseSummary(client, sessionId);

        await writeAuditLog(client, {
          actorUserId,
          actionType: "SessionClose",
          sessionId,
          oldValue: { state: session.state },
          newValue: {
            state: "Closed",
            closedAt: closedAt.toISOString(),
            closedByUserId: actorUserId,
            summary,
          },
        });

        const result: CloseSessionResult = {
          classSessionId: sessionId,
          state: "Closed",
          closedAt: closedAt.toISOString(),
          summary,
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

export type SessionLifecycleRepository = ReturnType<typeof createSessionLifecycleRepository>;
