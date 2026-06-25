import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Pool, PoolClient } from "pg";
import { getPool } from "../../db/pool.js";
import type {
  AuditLogRow,
  AuditWriteInput,
  ListAuditLogsQuery,
  ListStatusHistoryQuery,
} from "./types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

const STATUS_HISTORY_ENTITY_TYPES = ["Registration", "CheckinRecord"] as const;
const DEFAULT_LIMIT = 100;
const MAX_LIMIT = 500;

let schemaReady: Promise<void> | null = null;

export async function ensureAuditSchema(): Promise<void> {
  if (!schemaReady) {
    schemaReady = (async () => {
      const sql = await readFile(join(__dirname, "schema.sql"), "utf8");
      await getPool().query(sql);
    })();
  }
  await schemaReady;
}

function mapAuditLog(row: Record<string, unknown>): AuditLogRow {
  return {
    id: row.id as string,
    eventId: (row.event_id as string | null) ?? null,
    entityType: row.entity_type as string,
    entityId: row.entity_id as string,
    action: row.action as string,
    actorId: row.actor_id as string,
    actorRole: row.actor_role as string,
    reasonCode: (row.reason_code as string | null) ?? null,
    reasonText: (row.reason_text as string | null) ?? null,
    before: (row.before_json as Record<string, unknown>) ?? {},
    after: (row.after_json as Record<string, unknown>) ?? {},
    occurredAt: (row.occurred_at as Date).toISOString(),
  };
}

function clampLimit(limit: number | undefined): number {
  if (limit === undefined) {
    return DEFAULT_LIMIT;
  }
  if (!Number.isInteger(limit) || limit < 1) {
    return DEFAULT_LIMIT;
  }
  return Math.min(limit, MAX_LIMIT);
}

export async function insertAuditLog(
  input: AuditWriteInput,
  client: Pool | PoolClient = getPool(),
): Promise<void> {
  await client.query(
    `INSERT INTO audit_logs (
      event_id, entity_type, entity_id, action,
      actor_id, actor_role, reason_code, reason_text,
      before_json, after_json
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb)`,
    [
      input.eventId,
      input.entityType,
      input.entityId,
      input.action,
      input.actorId,
      input.actorRole,
      input.reasonCode ?? null,
      input.reasonText ?? null,
      JSON.stringify(input.before),
      JSON.stringify(input.after),
    ],
  );
}

export async function listAuditLogsForEvent(
  eventId: string,
  query: ListAuditLogsQuery = {},
  client: Pool | PoolClient = getPool(),
): Promise<AuditLogRow[]> {
  const params: unknown[] = [eventId];
  const conditions = ["event_id = $1"];
  let paramIndex = 2;

  if (query.entityType) {
    conditions.push(`entity_type = $${paramIndex++}`);
    params.push(query.entityType);
  }
  if (query.entityId) {
    conditions.push(`entity_id = $${paramIndex++}`);
    params.push(query.entityId);
  }

  params.push(clampLimit(query.limit));

  const result = await client.query(
    `SELECT *
     FROM audit_logs
     WHERE ${conditions.join(" AND ")}
     ORDER BY occurred_at DESC
     LIMIT $${paramIndex}`,
    params,
  );

  return result.rows.map((row) =>
    mapAuditLog(row as Record<string, unknown>),
  );
}

export async function listRegistrationStatusHistory(
  eventId: string,
  query: ListStatusHistoryQuery = {},
  client: Pool | PoolClient = getPool(),
): Promise<AuditLogRow[]> {
  const params: unknown[] = [eventId, STATUS_HISTORY_ENTITY_TYPES];
  const conditions = [
    "event_id = $1",
    "entity_type = ANY($2::text[])",
  ];
  let paramIndex = 3;

  if (query.registrationId) {
    conditions.push(
      `(entity_id = $${paramIndex}::uuid OR after_json->>'registrationId' = $${paramIndex}::text)`,
    );
    params.push(query.registrationId);
    paramIndex++;
  }

  params.push(clampLimit(query.limit));

  const result = await client.query(
    `SELECT *
     FROM audit_logs
     WHERE ${conditions.join(" AND ")}
     ORDER BY occurred_at ASC
     LIMIT $${paramIndex}`,
    params,
  );

  return result.rows.map((row) =>
    mapAuditLog(row as Record<string, unknown>),
  );
}

export async function countAuditLogsForEvent(
  eventId: string,
  client: Pool | PoolClient = getPool(),
): Promise<number> {
  const result = await client.query(
    "SELECT COUNT(*)::int AS count FROM audit_logs WHERE event_id = $1",
    [eventId],
  );
  return (result.rows[0] as { count: number }).count;
}
