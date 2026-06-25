import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { EventState } from "@we-event/domain";
import type { Pool, PoolClient } from "pg";
import { getPool } from "../../db/pool.js";
import { ensureAuditSchema, insertAuditLog } from "../audit/repository.js";
import type {
  CreateEventInput,
  EventRow,
  EventRuleConfigRow,
  EventWithConfig,
  RuleConfigInput,
  UpdateEventInput,
} from "./types.js";

export interface ListEventsOptions {
  states?: EventState[];
  state?: EventState;
  q?: string;
  sortColumn: string;
  sortDirection: "ASC" | "DESC";
  limit: number;
  offset: number;
}

export interface ListEventsResult {
  items: EventWithConfig[];
  total: number;
}

const __dirname = dirname(fileURLToPath(import.meta.url));

let schemaReady: Promise<void> | null = null;

export async function ensureEventSchema(): Promise<void> {
  if (!schemaReady) {
    schemaReady = (async () => {
      const sql = await readFile(join(__dirname, "schema.sql"), "utf8");
      await getPool().query(sql);
      await ensureAuditSchema();
    })();
  }
  await schemaReady;
}

function mapRuleConfig(row: Record<string, unknown>): EventRuleConfigRow {
  return {
    eventId: (row.event_id ?? row.id) as string,
    capacity: row.capacity as number,
    waitlistEnabled: row.waitlist_enabled as boolean,
    registrationOpenAt: (row.registration_open_at as Date).toISOString(),
    registrationCloseAt: (row.registration_close_at as Date).toISOString(),
    checkinOpenAt: (row.checkin_open_at as Date).toISOString(),
    checkinCloseAt: (row.checkin_close_at as Date).toISOString(),
    feedbackRequired: row.feedback_required as boolean,
    feedbackOpenAt: (row.feedback_open_at as Date).toISOString(),
    feedbackCloseAt: (row.feedback_close_at as Date).toISOString(),
    registrationPaused: row.registration_paused as boolean,
    version: (row.rule_version ?? row.version) as number,
  };
}

function mapEvent(row: Record<string, unknown>): EventRow {
  return {
    id: row.id as string,
    organizationId: row.organization_id as string,
    name: row.name as string,
    description: row.description as string,
    location: row.location as string,
    state: row.state as EventState,
    startAt: (row.start_at as Date).toISOString(),
    endAt: (row.end_at as Date).toISOString(),
    coverImageKey: (row.cover_image_key as string | null) ?? null,
    coverImageUpdatedAt: row.cover_image_updated_at
      ? (row.cover_image_updated_at as Date).toISOString()
      : null,
    createdBy: row.created_by as string,
    updatedBy: row.updated_by as string,
    createdAt: (row.created_at as Date).toISOString(),
    updatedAt: (row.updated_at as Date).toISOString(),
    version: row.version as number,
  };
}

function mapEventWithConfig(row: Record<string, unknown>): EventWithConfig {
  return {
    ...mapEvent(row),
    ruleConfig: mapRuleConfig(row),
  };
}

const EVENT_SELECT = `
  SELECT
    e.id,
    e.organization_id,
    e.name,
    e.description,
    e.location,
    e.state,
    e.start_at,
    e.end_at,
    e.cover_image_key,
    e.cover_image_updated_at,
    e.created_by,
    e.updated_by,
    e.created_at,
    e.updated_at,
    e.version,
    c.event_id,
    c.capacity,
    c.waitlist_enabled,
    c.registration_open_at,
    c.registration_close_at,
    c.checkin_open_at,
    c.checkin_close_at,
    c.feedback_required,
    c.feedback_open_at,
    c.feedback_close_at,
    c.registration_paused,
    c.version AS rule_version
  FROM events e
  INNER JOIN event_rule_configs c ON c.event_id = e.id
`;


async function queryOne(
  client: Pool | PoolClient,
  sql: string,
  params: unknown[],
): Promise<EventWithConfig | null> {
  const result = await client.query(sql, params);
  if (result.rowCount === 0) {
    return null;
  }
  const row = result.rows[0] as Record<string, unknown>;
  return mapEventWithConfig(row);
}

export async function findEventById(
  eventId: string,
  client: Pool | PoolClient = getPool(),
): Promise<EventWithConfig | null> {
  return queryOne(client, `${EVENT_SELECT} WHERE e.id = $1`, [eventId]);
}

export async function listEvents(
  options: ListEventsOptions,
  client: Pool | PoolClient = getPool(),
): Promise<ListEventsResult> {
  const params: unknown[] = [];
  const conditions: string[] = [];
  let paramIndex = 1;

  if (options.states && options.states.length > 0) {
    conditions.push(`e.state = ANY($${paramIndex++}::text[])`);
    params.push(options.states);
  }

  if (options.state) {
    conditions.push(`e.state = $${paramIndex++}`);
    params.push(options.state);
  }

  if (options.q?.trim()) {
    const pattern = `%${options.q.trim()}%`;
    conditions.push(
      `(e.name ILIKE $${paramIndex} OR e.location ILIKE $${paramIndex} OR e.description ILIKE $${paramIndex})`,
    );
    params.push(pattern);
    paramIndex += 1;
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

  const countResult = await client.query(
    `SELECT COUNT(*)::int AS total FROM events e ${where}`,
    params,
  );
  const total = (countResult.rows[0] as { total: number }).total;

  const sortColumn = options.sortColumn;
  const sortDirection = options.sortDirection;
  const listParams = [...params, options.limit, options.offset];

  const result = await client.query(
    `${EVENT_SELECT} ${where}
     ORDER BY ${sortColumn} ${sortDirection}
     LIMIT $${paramIndex++} OFFSET $${paramIndex}`,
    listParams,
  );

  return {
    items: result.rows.map((row) =>
      mapEventWithConfig(row as Record<string, unknown>),
    ),
    total,
  };
}

export async function organizationExists(
  organizationId: string,
  client: Pool | PoolClient = getPool(),
): Promise<boolean> {
  const result = await client.query(
    "SELECT 1 FROM organizations WHERE id = $1",
    [organizationId],
  );
  return (result.rowCount ?? 0) > 0;
}

export async function createEvent(
  input: CreateEventInput,
  actorId: string,
  actorRole: string,
  organizationId: string,
): Promise<EventWithConfig> {
  const pool = getPool();
  const client = await pool.connect();
  try {
    await client.query("BEGIN");

    const eventResult = await client.query(
      `INSERT INTO events (
        organization_id, name, description, location,
        state, start_at, end_at, created_by, updated_by
      ) VALUES ($1, $2, $3, $4, 'Draft', $5, $6, $7, $7)
      RETURNING *`,
      [
        organizationId,
        input.name,
        input.description ?? "",
        input.location ?? "",
        input.startAt,
        input.endAt,
        actorId,
      ],
    );

    const event = mapEvent(eventResult.rows[0] as Record<string, unknown>);
    const rule = input.ruleConfig;

    await client.query(
      `INSERT INTO event_rule_configs (
        event_id, capacity, waitlist_enabled,
        registration_open_at, registration_close_at,
        checkin_open_at, checkin_close_at,
        feedback_required, feedback_open_at, feedback_close_at
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
      [
        event.id,
        rule.capacity,
        rule.waitlistEnabled ?? false,
        rule.registrationOpenAt,
        rule.registrationCloseAt,
        rule.checkinOpenAt,
        rule.checkinCloseAt,
        rule.feedbackRequired ?? false,
        rule.feedbackOpenAt,
        rule.feedbackCloseAt,
      ],
    );

    await insertAuditLog(
      {
        eventId: event.id,
        entityType: "Event",
        entityId: event.id,
        action: "event.created",
        actorId,
        actorRole,
        before: {},
        after: { eventId: event.id, state: event.state, name: event.name },
      },
      client,
    );

    await client.query("COMMIT");

    const created = await findEventById(event.id, client);
    if (!created) {
      throw new Error("Failed to load created event");
    }
    return created;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

export async function updateEvent(
  eventId: string,
  input: UpdateEventInput,
  actorId: string,
  actorRole: string,
): Promise<EventWithConfig | null> {
  const pool = getPool();
  const client = await pool.connect();
  try {
    await client.query("BEGIN");

    const existing = await findEventById(eventId, client);
    if (!existing) {
      await client.query("ROLLBACK");
      return null;
    }

    const eventFields: string[] = [];
    const eventParams: unknown[] = [];
    let paramIndex = 1;

    if (input.name !== undefined) {
      eventFields.push(`name = $${paramIndex++}`);
      eventParams.push(input.name);
    }
    if (input.description !== undefined) {
      eventFields.push(`description = $${paramIndex++}`);
      eventParams.push(input.description);
    }
    if (input.location !== undefined) {
      eventFields.push(`location = $${paramIndex++}`);
      eventParams.push(input.location);
    }
    if (input.startAt !== undefined) {
      eventFields.push(`start_at = $${paramIndex++}`);
      eventParams.push(input.startAt);
    }
    if (input.endAt !== undefined) {
      eventFields.push(`end_at = $${paramIndex++}`);
      eventParams.push(input.endAt);
    }

    if (eventFields.length > 0) {
      eventFields.push(`updated_by = $${paramIndex++}`);
      eventParams.push(actorId);
      eventFields.push(`updated_at = NOW()`);
      eventFields.push(`version = version + 1`);
      eventParams.push(eventId);

      await client.query(
        `UPDATE events SET ${eventFields.join(", ")} WHERE id = $${paramIndex}`,
        eventParams,
      );
    }

    if (input.ruleConfig) {
      const ruleFields: string[] = [];
      const ruleParams: unknown[] = [];
      let ruleIndex = 1;
      const rule = input.ruleConfig;

      const ruleColumnMap: Record<string, unknown> = {
        capacity: rule.capacity,
        waitlist_enabled: rule.waitlistEnabled,
        registration_open_at: rule.registrationOpenAt,
        registration_close_at: rule.registrationCloseAt,
        checkin_open_at: rule.checkinOpenAt,
        checkin_close_at: rule.checkinCloseAt,
        feedback_required: rule.feedbackRequired,
        feedback_open_at: rule.feedbackOpenAt,
        feedback_close_at: rule.feedbackCloseAt,
        registration_paused: rule.registrationPaused,
      };

      for (const [column, value] of Object.entries(ruleColumnMap)) {
        if (value !== undefined) {
          ruleFields.push(`${column} = $${ruleIndex++}`);
          ruleParams.push(value);
        }
      }

      if (ruleFields.length > 0) {
        ruleFields.push("version = version + 1");
        ruleParams.push(eventId);
        await client.query(
          `UPDATE event_rule_configs SET ${ruleFields.join(", ")} WHERE event_id = $${ruleIndex}`,
          ruleParams,
        );

        await insertAuditLog(
          {
            eventId,
            entityType: "EventRuleConfig",
            entityId: eventId,
            action: "event.rule_config.updated",
            actorId,
            actorRole,
            reasonCode: input.reasonCode ?? null,
            reasonText: input.reasonText ?? null,
            before: existing.ruleConfig as unknown as Record<string, unknown>,
            after: { ...existing.ruleConfig, ...input.ruleConfig },
          },
          client,
        );
      }
    }

    if (eventFields.length > 0) {
      await insertAuditLog(
        {
          eventId,
          entityType: "Event",
          entityId: eventId,
          action: "event.updated",
          actorId,
          actorRole,
          before: {
            name: existing.name,
            description: existing.description,
            location: existing.location,
            startAt: existing.startAt,
            endAt: existing.endAt,
          },
          after: {
            name: input.name ?? existing.name,
            description: input.description ?? existing.description,
            location: input.location ?? existing.location,
            startAt: input.startAt ?? existing.startAt,
            endAt: input.endAt ?? existing.endAt,
          },
        },
        client,
      );
    }

    await client.query("COMMIT");
    const updated = await findEventById(eventId);
    if (!updated) {
      throw new Error("Failed to load updated event");
    }
    return updated;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

export async function transitionEventState(
  eventId: string,
  toState: EventState,
  context: {
    actorId: string;
    actorRole: string;
    action: string;
    reasonCode?: string;
    reasonText?: string;
    rulePatch?: Partial<RuleConfigInput> & { registrationPaused?: boolean };
  },
): Promise<EventWithConfig | null> {
  const pool = getPool();
  const client = await pool.connect();
  try {
    await client.query("BEGIN");

    const existing = await findEventById(eventId, client);
    if (!existing) {
      await client.query("ROLLBACK");
      return null;
    }

    const fromState = existing.state;

    await client.query(
      `UPDATE events
       SET state = $1, updated_by = $2, updated_at = NOW(), version = version + 1
       WHERE id = $3`,
      [toState, context.actorId, eventId],
    );

    if (context.rulePatch && Object.keys(context.rulePatch).length > 0) {
      const ruleFields: string[] = [];
      const ruleParams: unknown[] = [];
      let idx = 1;
      const patch = context.rulePatch;

      if (patch.registrationPaused !== undefined) {
        ruleFields.push(`registration_paused = $${idx++}`);
        ruleParams.push(patch.registrationPaused);
      }

      if (ruleFields.length > 0) {
        ruleFields.push("version = version + 1");
        ruleParams.push(eventId);
        await client.query(
          `UPDATE event_rule_configs SET ${ruleFields.join(", ")} WHERE event_id = $${idx}`,
          ruleParams,
        );
      }
    }

    await insertAuditLog(
      {
        eventId,
        entityType: "Event",
        entityId: eventId,
        action: context.action,
        actorId: context.actorId,
        actorRole: context.actorRole,
        reasonCode: context.reasonCode ?? null,
        reasonText: context.reasonText ?? null,
        before: { state: fromState, ruleConfig: existing.ruleConfig },
        after: {
          state: toState,
          ruleConfig: context.rulePatch
            ? { ...existing.ruleConfig, ...context.rulePatch }
            : existing.ruleConfig,
        },
      },
      client,
    );

    await client.query("COMMIT");
    return findEventById(eventId);
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

export async function setEventCoverImage(
  eventId: string,
  coverImageKey: string,
  actorId: string,
  actorRole: string,
  previousKey: string | null,
): Promise<EventWithConfig | null> {
  const pool = getPool();
  const client = await pool.connect();
  try {
    await client.query("BEGIN");

    const existing = await findEventById(eventId, client);
    if (!existing) {
      await client.query("ROLLBACK");
      return null;
    }

    await client.query(
      `UPDATE events
       SET cover_image_key = $1,
           cover_image_updated_at = NOW(),
           updated_by = $2,
           updated_at = NOW(),
           version = version + 1
       WHERE id = $3`,
      [coverImageKey, actorId, eventId],
    );

    await insertAuditLog(
      {
        eventId,
        entityType: "Event",
        entityId: eventId,
        action: "event.cover_image.uploaded",
        actorId,
        actorRole,
        before: { coverImageKey: previousKey },
        after: { coverImageKey },
      },
      client,
    );

    await client.query("COMMIT");
    return findEventById(eventId, client);
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

export async function clearEventCoverImage(
  eventId: string,
  actorId: string,
  actorRole: string,
  previousKey: string | null,
): Promise<EventWithConfig | null> {
  const pool = getPool();
  const client = await pool.connect();
  try {
    await client.query("BEGIN");

    const existing = await findEventById(eventId, client);
    if (!existing) {
      await client.query("ROLLBACK");
      return null;
    }

    await client.query(
      `UPDATE events
       SET cover_image_key = NULL,
           cover_image_updated_at = NULL,
           updated_by = $1,
           updated_at = NOW(),
           version = version + 1
       WHERE id = $2`,
      [actorId, eventId],
    );

    await insertAuditLog(
      {
        eventId,
        entityType: "Event",
        entityId: eventId,
        action: "event.cover_image.deleted",
        actorId,
        actorRole,
        before: { coverImageKey: previousKey },
        after: { coverImageKey: null },
      },
      client,
    );

    await client.query("COMMIT");
    return findEventById(eventId, client);
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

