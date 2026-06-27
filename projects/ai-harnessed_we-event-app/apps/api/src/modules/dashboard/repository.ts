import type { Pool, PoolClient } from "pg";
import { getPool } from "../../db/pool.js";
import { ensureFeedbackSchema } from "../feedback/repository.js";

let schemaReady: Promise<void> | null = null;

export async function ensureDashboardSchema(): Promise<void> {
  if (!schemaReady) {
    schemaReady = ensureFeedbackSchema();
  }
  await schemaReady;
}

export async function countFeedbackSubmissionsForEvent(
  eventId: string,
  client: Pool | PoolClient = getPool(),
): Promise<number> {
  const result = await client.query(
    `SELECT COUNT(*)::int AS total
     FROM feedback_submissions
     WHERE event_id = $1`,
    [eventId],
  );
  return (result.rows[0] as { total: number }).total;
}
