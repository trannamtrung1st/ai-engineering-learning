import { createHash, randomUUID } from "node:crypto";
import type pg from "pg";
import type { CurrentQrResult, ResolvedQrToken } from "./types.js";

export const QR_TTL_MS = 30_000;

export function hashQrToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

function isSha256Hex(value: string): boolean {
  return /^[a-f0-9]{64}$/i.test(value);
}

function mapTokenRow(row: {
  id: string;
  class_session_id: string;
  state: string;
  token_hash: string;
  issued_at: Date;
  expires_at: Date;
}): ResolvedQrToken {
  const now = Date.now();
  const expiresMs = row.expires_at.getTime();
  let state = row.state as ResolvedQrToken["state"];
  if (state === "Valid" && expiresMs <= now) {
    state = "Expired";
  }
  return {
    id: row.id,
    classSessionId: row.class_session_id,
    state,
    issuedAt: row.issued_at.toISOString(),
    expiresAt: row.expires_at.toISOString(),
  };
}

export async function issueQrToken(
  client: pg.PoolClient,
  sessionId: string,
): Promise<{ expiresAt: string; qrPayload: string; tokenId: string }> {
  const token = randomUUID();
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
    [tokenId, sessionId, token, issuedAt.toISOString(), expiresAt.toISOString()],
  );

  return { expiresAt: expiresAt.toISOString(), qrPayload: token, tokenId };
}

export async function resolveQrToken(
  query: pg.Pool | pg.PoolClient,
  qrToken: string,
): Promise<ResolvedQrToken | null> {
  const hashed = hashQrToken(qrToken);
  const result = await query.query<{
    id: string;
    class_session_id: string;
    state: string;
    token_hash: string;
    issued_at: Date;
    expires_at: Date;
  }>(
    `
    SELECT id, class_session_id, state, token_hash, issued_at, expires_at
    FROM qr_session_tokens
    WHERE token_hash = $1 OR token_hash = $2
    `,
    [qrToken, hashed],
  );
  const row = result.rows[0];
  return row ? mapTokenRow(row) : null;
}

export async function getOrRotateCurrentQr(
  client: pg.PoolClient,
  sessionId: string,
): Promise<CurrentQrResult> {
  const now = new Date();
  const existing = await client.query<{
    id: string;
    token_hash: string;
    expires_at: Date;
  }>(
    `
    SELECT id, token_hash, expires_at
    FROM qr_session_tokens
    WHERE class_session_id = $1 AND state = 'Valid' AND expires_at > $2
    ORDER BY issued_at DESC
    LIMIT 1
    FOR UPDATE
    `,
    [sessionId, now.toISOString()],
  );

  const row = existing.rows[0];
  if (row && !isSha256Hex(row.token_hash)) {
    return {
      classSessionId: sessionId,
      tokenState: "Valid",
      expiresAt: row.expires_at.toISOString(),
      qrPayload: row.token_hash,
    };
  }

  if (row && isSha256Hex(row.token_hash)) {
    await client.query(`UPDATE qr_session_tokens SET state = 'Expired' WHERE id = $1`, [row.id]);
  }

  const issued = await issueQrToken(client, sessionId);
  return {
    classSessionId: sessionId,
    tokenState: "Valid",
    expiresAt: issued.expiresAt,
    qrPayload: issued.qrPayload,
  };
}
