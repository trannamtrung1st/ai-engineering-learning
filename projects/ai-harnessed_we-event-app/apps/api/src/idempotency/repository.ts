import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Pool, PoolClient } from "pg";
import { getPool } from "../db/pool.js";
import { ApiError } from "../errors/api-error.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

let schemaReady: Promise<void> | null = null;

export async function ensureIdempotencySchema(): Promise<void> {
  if (!schemaReady) {
    schemaReady = (async () => {
      const sql = await readFile(join(__dirname, "schema.sql"), "utf8");
      await getPool().query(sql);
    })();
  }
  await schemaReady;
}

interface IdempotencyRecord {
  requestFingerprint: string;
  responseStatus: number;
  responseBody: unknown;
}

export async function findIdempotencyRecord(
  actorId: string,
  idempotencyKey: string,
  operationScope: string,
  client: Pool | PoolClient = getPool(),
): Promise<IdempotencyRecord | null> {
  const result = await client.query(
    `SELECT request_fingerprint, response_status, response_body
     FROM idempotency_keys
     WHERE actor_id = $1 AND idempotency_key = $2 AND operation_scope = $3`,
    [actorId, idempotencyKey, operationScope],
  );

  if (result.rowCount === 0) {
    return null;
  }

  const row = result.rows[0] as {
    request_fingerprint: string;
    response_status: number;
    response_body: unknown;
  };

  return {
    requestFingerprint: row.request_fingerprint,
    responseStatus: row.response_status,
    responseBody: row.response_body,
  };
}

export async function saveIdempotencyRecord(
  actorId: string,
  idempotencyKey: string,
  operationScope: string,
  requestFingerprint: string,
  responseStatus: number,
  responseBody: unknown,
  client: Pool | PoolClient = getPool(),
): Promise<void> {
  await client.query(
    `INSERT INTO idempotency_keys (
      actor_id, idempotency_key, operation_scope,
      request_fingerprint, response_status, response_body
    ) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
    ON CONFLICT (actor_id, idempotency_key, operation_scope) DO NOTHING`,
    [
      actorId,
      idempotencyKey,
      operationScope,
      requestFingerprint,
      responseStatus,
      JSON.stringify(responseBody),
    ],
  );
}

function readIdempotencyKey(
  headers: Record<string, string | string[] | undefined>,
): string | undefined {
  const raw = headers["idempotency-key"];
  if (typeof raw === "string" && raw.trim().length > 0) {
    return raw.trim();
  }
  return undefined;
}

export async function executeIdempotent<T>(
  headers: Record<string, string | string[] | undefined>,
  actorId: string,
  operationScope: string,
  requestFingerprint: string,
  execute: () => Promise<T>,
): Promise<T> {
  const idempotencyKey = readIdempotencyKey(headers);
  if (!idempotencyKey) {
    return execute();
  }

  const existing = await findIdempotencyRecord(
    actorId,
    idempotencyKey,
    operationScope,
  );

  if (existing) {
    if (existing.requestFingerprint !== requestFingerprint) {
      throw new ApiError({
        code: "IDEMPOTENCY_KEY_CONFLICT",
        message:
          "This idempotency key was already used with a different request.",
        statusCode: 409,
        details: { operationScope },
      });
    }
    return existing.responseBody as T;
  }

  const result = await execute();

  await saveIdempotencyRecord(
    actorId,
    idempotencyKey,
    operationScope,
    requestFingerprint,
    200,
    result,
  );

  return result;
}
