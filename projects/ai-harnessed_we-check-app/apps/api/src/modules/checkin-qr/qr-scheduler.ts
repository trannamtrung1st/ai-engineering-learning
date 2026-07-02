import { randomUUID } from "node:crypto";
import {
  QR_TOKEN_TTL_MS,
  QrTokenStatus,
  computeNominalWindowEnd,
} from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { now } from "../../infra/clock.js";

export interface QrTokenDisplayDto {
  sessionId: string;
  tokenId: string;
  qrPayload: string;
  issuedAt: string;
  expiresAt: string;
  secondsRemaining: number;
  attendanceWindowClosesAt: string;
}

const ROTATION_INTERVAL_MS = QR_TOKEN_TTL_MS;

export class QrScheduler {
  private readonly intervals = new Map<string, ReturnType<typeof setInterval>>();
  private protectedTokenIds = new Set<string>();

  constructor(private readonly db: DbPool) {}

  /** Browser-gate fixture tokens — excluded from rotation expiry (NFR-06). */
  setProtectedTokenIds(tokenIds: readonly string[]): void {
    this.protectedTokenIds = new Set(tokenIds);
  }

  start(sessionId: string): void {
    if (this.intervals.has(sessionId)) {
      return;
    }
    void this.rotate(sessionId);
    const handle = setInterval(() => {
      void this.rotate(sessionId);
    }, ROTATION_INTERVAL_MS);
    handle.unref();
    this.intervals.set(sessionId, handle);
  }

  async stop(sessionId: string): Promise<void> {
    const handle = this.intervals.get(sessionId);
    if (handle) {
      clearInterval(handle);
      this.intervals.delete(sessionId);
    }
    await this.expireValidTokens(sessionId);
  }

  async stopAll(): Promise<void> {
    const sessionIds = [...this.intervals.keys()];
    await Promise.all(sessionIds.map((sessionId) => this.stop(sessionId)));
  }

  async rotate(sessionId: string): Promise<void> {
    const current = now();
    const protectedIds = [...this.protectedTokenIds];
    if (protectedIds.length > 0) {
      await this.db.query(
        `UPDATE qr_tokens SET status = $2
         WHERE session_id = $1 AND status = $3 AND NOT (id = ANY($4::uuid[]))`,
        [sessionId, QrTokenStatus.Expired, QrTokenStatus.Valid, protectedIds],
      );
    } else {
      await this.db.query(
        `UPDATE qr_tokens SET status = $2
         WHERE session_id = $1 AND status = $3`,
        [sessionId, QrTokenStatus.Expired, QrTokenStatus.Valid],
      );
    }

    const tokenId = randomUUID();
    const expiresAt = new Date(current.getTime() + QR_TOKEN_TTL_MS);
    await this.db.query(
      `INSERT INTO qr_tokens (id, session_id, status, issued_at, expires_at)
       VALUES ($1, $2, $3, $4, $5)`,
      [tokenId, sessionId, QrTokenStatus.Valid, current, expiresAt],
    );
  }

  async expireValidTokens(sessionId: string): Promise<void> {
    await this.db.query(
      `UPDATE qr_tokens SET status = $2
       WHERE session_id = $1 AND status = $3`,
      [sessionId, QrTokenStatus.Expired, QrTokenStatus.Valid],
    );
  }

  async getCurrentToken(
    sessionId: string,
    scheduledStart: Date,
  ): Promise<QrTokenDisplayDto | null> {
    const current = now();
    const protectedIds = [...this.protectedTokenIds];
    const params: unknown[] = [sessionId, QrTokenStatus.Valid];
    let sql = `SELECT id, issued_at, expires_at
       FROM qr_tokens
       WHERE session_id = $1 AND status = $2`;
    if (protectedIds.length > 0) {
      sql += ` AND NOT (id = ANY($3::uuid[]))`;
      params.push(protectedIds);
    }
    sql += ` ORDER BY issued_at DESC LIMIT 1`;

    const result = await this.db.query<{
      id: string;
      issued_at: Date;
      expires_at: Date;
    }>(sql, params);

    const row = result.rows[0];
    if (!row) {
      return null;
    }

    const secondsRemaining = Math.max(
      0,
      Math.ceil((row.expires_at.getTime() - current.getTime()) / 1000),
    );

    return {
      sessionId,
      tokenId: row.id,
      qrPayload: `wecheck://check-in?token=${row.id}&session=${sessionId}`,
      issuedAt: row.issued_at.toISOString(),
      expiresAt: row.expires_at.toISOString(),
      secondsRemaining,
      attendanceWindowClosesAt: computeNominalWindowEnd(scheduledStart).toISOString(),
    };
  }
}
