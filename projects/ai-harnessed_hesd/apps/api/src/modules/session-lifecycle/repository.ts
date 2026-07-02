import { createHash, randomUUID } from "node:crypto";
import type pg from "pg";
import { createAttendanceLedgerRepository } from "../attendance-ledger/repository.js";
import { writeAuditEvent } from "../audit-and-compliance/service.js";
import {
  createRealtimeDeliveryRepository,
  recordQrTokenIssuedTelemetry,
  recordSessionLifecycleTelemetry,
} from "../realtime-delivery/repository.js";
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
  const attendanceLedger = createAttendanceLedgerRepository(pool);
  const realtimeDelivery = createRealtimeDeliveryRepository(pool);
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
  ): Promise<{ expiresAt: string; issuedAt: string; qrPayload: string; tokenId: string }> {
    const token = randomUUID();
    const tokenHash = hashToken(token);
    const issuedAt = new Date();
    const expiresAt = new Date(issuedAt.getTime() + QR_TTL_MS);
    const tokenId = randomUUID();

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
      [tokenId, sessionId, tokenHash, issuedAt.toISOString(), expiresAt.toISOString()],
    );

    return {
      expiresAt: expiresAt.toISOString(),
      issuedAt: issuedAt.toISOString(),
      qrPayload: token,
      tokenId,
    };
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

  async function writeAuditLog(
    client: pg.PoolClient,
    params: {
      actorUserId: string;
      actionType: "SessionOpen" | "SessionClose";
      sessionId: string;
      oldValue: Record<string, unknown> | null;
      newValue: Record<string, unknown>;
      correlationId?: string | null;
    },
  ): Promise<void> {
    await writeAuditEvent(client, {
      actorUserId: params.actorUserId,
      actionType: params.actionType,
      targetType: "ClassSession",
      targetId: params.sessionId,
      oldValue: params.oldValue,
      newValue: params.newValue,
      correlationId: params.correlationId ?? null,
    });
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
      options: { roomId?: string | null; idempotencyKey?: string; correlationId?: string | null } = {},
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
          qr: {
            expiresAt: qr.expiresAt,
            qrPayload: qr.qrPayload,
          },
        };

        if (cacheKey) {
          idempotencyCache.set(cacheKey, result);
        }

        await client.query("COMMIT");
        recordQrTokenIssuedTelemetry({
          classSessionId: sessionId,
          tokenId: qr.tokenId,
          issuedAt: qr.issuedAt,
          expiresAt: qr.expiresAt,
          ttlMs: QR_TTL_MS,
          correlationId: options.correlationId,
        });
        const rosterEvent = await realtimeDelivery.publishRosterUpdate({
          classSessionId: sessionId,
          reason: "SessionOpened",
          correlationId: options.correlationId,
        });
        recordSessionLifecycleTelemetry({
          type: "SessionOpened",
          classSessionId: sessionId,
          actorUserId,
          beforeState: session.state,
          afterState: "Open",
          correlationId: options.correlationId,
          initialRosterCount: rosterEvent?.roster.rows.length,
        });
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
      options: { idempotencyKey?: string; correlationId?: string | null } = {},
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
        await attendanceLedger.finalizeAbsentStudents(client, session, actorUserId, {
          correlationId: options.correlationId ?? sessionId,
        });

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
          correlationId: options.correlationId ?? null,
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
        await realtimeDelivery.publishRosterUpdate({
          classSessionId: sessionId,
          reason: "SessionClosed",
          correlationId: options.correlationId,
        });
        recordSessionLifecycleTelemetry({
          type: "SessionClosed",
          classSessionId: sessionId,
          actorUserId,
          beforeState: session.state,
          afterState: "Closed",
          correlationId: options.correlationId,
        });
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
