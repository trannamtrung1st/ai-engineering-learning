import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  VALIDATION_ERROR_CODES,
  type RegistrationState,
} from "@we-event/domain";
import type { Pool, PoolClient, QueryResult } from "pg";
import { getPool } from "../../db/pool.js";
import { ApiError } from "../../errors/api-error.js";
import { insertAuditLog } from "../event/repository.js";
import type {
  ActorContext,
  RegistrationAuditInput,
  RegistrationRow,
  RegistrationWithWaitlist,
  WaitlistEntryRow,
} from "./types.js";
import { SEAT_HOLDING_STATES } from "./validation.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

let schemaReady: Promise<void> | null = null;

export async function ensureRegistrationSchema(): Promise<void> {
  if (!schemaReady) {
    schemaReady = (async () => {
      const sql = await readFile(join(__dirname, "schema.sql"), "utf8");
      await getPool().query(sql);
    })();
  }
  await schemaReady;
}

function mapRegistration(row: Record<string, unknown>): RegistrationRow {
  return {
    id: row.id as string,
    eventId: row.event_id as string,
    participantId: row.participant_id as string,
    state: row.state as RegistrationState,
    requestedAt: (row.requested_at as Date).toISOString(),
    cancelledAt: row.cancelled_at
      ? (row.cancelled_at as Date).toISOString()
      : null,
    statusReasonCode: (row.status_reason_code as string | null) ?? null,
    statusReasonText: (row.status_reason_text as string | null) ?? null,
    createdAt: (row.created_at as Date).toISOString(),
    updatedAt: (row.updated_at as Date).toISOString(),
    version: row.version as number,
  };
}

function mapWaitlistEntry(row: Record<string, unknown>): WaitlistEntryRow {
  return {
    id: row.id as string,
    eventId: row.event_id as string,
    registrationId: row.registration_id as string,
    position: row.position as number,
    enqueuedAt: (row.enqueued_at as Date).toISOString(),
    promotedAt: row.promoted_at
      ? (row.promoted_at as Date).toISOString()
      : null,
    expiredAt: row.expired_at
      ? (row.expired_at as Date).toISOString()
      : null,
  };
}

async function writeRegistrationAudit(
  input: RegistrationAuditInput,
  client: Pool | PoolClient,
): Promise<void> {
  await insertAuditLog(
    {
      eventId: input.eventId,
      entityType: "Registration",
      entityId: input.registrationId,
      action: input.action,
      actorId: input.actorId,
      actorRole: input.actorRole,
      reasonCode: input.reasonCode ?? null,
      reasonText: input.reasonText ?? null,
      before: input.before,
      after: input.after,
    },
    client,
  );
}

export async function findActiveRegistration(
  eventId: string,
  participantId: string,
  client: Pool | PoolClient = getPool(),
): Promise<RegistrationRow | null> {
  const result = await client.query(
    `SELECT *
     FROM registrations
     WHERE event_id = $1
       AND participant_id = $2
       AND state IN ('Requested', 'Registered', 'Waitlisted', 'CheckedIn')
     ORDER BY requested_at DESC
     LIMIT 1`,
    [eventId, participantId],
  );
  if (result.rowCount === 0) {
    return null;
  }
  return mapRegistration(result.rows[0] as Record<string, unknown>);
}

export async function findRegistrationById(
  registrationId: string,
  client: Pool | PoolClient = getPool(),
): Promise<RegistrationRow | null> {
  const result = await client.query(
    "SELECT * FROM registrations WHERE id = $1",
    [registrationId],
  );
  if (result.rowCount === 0) {
    return null;
  }
  return mapRegistration(result.rows[0] as Record<string, unknown>);
}

export async function findRegistrationByParticipant(
  eventId: string,
  participantId: string,
  states: RegistrationState[],
  client: Pool | PoolClient = getPool(),
): Promise<RegistrationRow | null> {
  if (states.length === 0) {
    return null;
  }

  const result = await client.query(
    `SELECT *
     FROM registrations
     WHERE event_id = $1
       AND participant_id = $2
       AND state = ANY($3::text[])
     ORDER BY requested_at DESC
     LIMIT 1`,
    [eventId, participantId, states],
  );
  if (result.rowCount === 0) {
    return null;
  }
  return mapRegistration(result.rows[0] as Record<string, unknown>);
}

export async function countSeatHolders(
  eventId: string,
  client: Pool | PoolClient,
): Promise<number> {
  const result = await client.query(
    `SELECT COUNT(*)::int AS count
     FROM registrations
     WHERE event_id = $1 AND state = ANY($2::text[])`,
    [eventId, SEAT_HOLDING_STATES],
  );
  return (result.rows[0] as { count: number }).count;
}

async function lockEventRuleConfig(
  eventId: string,
  client: PoolClient,
): Promise<void> {
  await client.query(
    "SELECT event_id FROM event_rule_configs WHERE event_id = $1 FOR UPDATE",
    [eventId],
  );
}

async function nextWaitlistPosition(
  eventId: string,
  client: PoolClient,
): Promise<number> {
  const result = await client.query(
    `SELECT COALESCE(MAX(position), 0) + 1 AS next_position
     FROM waitlist_entries
     WHERE event_id = $1
       AND promoted_at IS NULL
       AND expired_at IS NULL`,
    [eventId],
  );
  return (result.rows[0] as { next_position: number }).next_position;
}

async function getWaitlistPosition(
  registrationId: string,
  client: Pool | PoolClient = getPool(),
): Promise<number | null> {
  const result = await client.query(
    `SELECT position
     FROM waitlist_entries
     WHERE registration_id = $1
       AND promoted_at IS NULL
       AND expired_at IS NULL`,
    [registrationId],
  );
  if (result.rowCount === 0) {
    return null;
  }
  return (result.rows[0] as { position: number }).position;
}

function isUniqueViolation(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code: string }).code === "23505"
  );
}

export async function createRegistration(
  eventId: string,
  participantId: string,
  context: ActorContext,
): Promise<RegistrationWithWaitlist> {
  const pool = getPool();
  const client = await pool.connect();

  try {
    await client.query("BEGIN");
    await lockEventRuleConfig(eventId, client);

    const existing = await findActiveRegistration(eventId, participantId, client);
    if (existing) {
      throw new ApiError({
        code: VALIDATION_ERROR_CODES.REGISTRATION_DUPLICATE_ACTIVE,
        message: "You already have an active registration for this event.",
        statusCode: 409,
        details: {
          registrationId: existing.id,
          state: existing.state,
        },
      });
    }

    const ruleResult = await client.query(
      "SELECT capacity, waitlist_enabled FROM event_rule_configs WHERE event_id = $1",
      [eventId],
    );
    const { capacity, waitlist_enabled: waitlistEnabled } = ruleResult.rows[0] as {
      capacity: number;
      waitlist_enabled: boolean;
    };
    const registeredCount = await countSeatHolders(eventId, client);

    let targetState: RegistrationState;
    if (registeredCount < capacity) {
      targetState = "Registered";
    } else if (waitlistEnabled) {
      targetState = "Waitlisted";
    } else {
      throw new ApiError({
        code: VALIDATION_ERROR_CODES.REGISTRATION_REJECTED_FULL,
        message: "Event is full and waitlist is not enabled.",
        statusCode: 422,
        details: { capacity, registeredCount },
      });
    }

    let insertResult: QueryResult;
    try {
      insertResult = await client.query(
        `INSERT INTO registrations (event_id, participant_id, state)
         VALUES ($1, $2, $3)
         RETURNING *`,
        [eventId, participantId, targetState],
      );
    } catch (error) {
      if (isUniqueViolation(error)) {
        throw new ApiError({
          code: VALIDATION_ERROR_CODES.REGISTRATION_DUPLICATE_ACTIVE,
          message: "You already have an active registration for this event.",
          statusCode: 409,
        });
      }
      throw error;
    }

    const registration = mapRegistration(
      insertResult.rows[0] as Record<string, unknown>,
    );

    if (targetState === "Registered") {
      const postCount = await countSeatHolders(eventId, client);
      if (postCount > capacity) {
        throw new ApiError({
          code: VALIDATION_ERROR_CODES.CAPACITY_EXCEEDED,
          message: "Event capacity has been exceeded.",
          statusCode: 422,
          details: { capacity, registeredCount: postCount },
        });
      }
    }

    let waitlistPosition: number | null = null;
    if (targetState === "Waitlisted") {
      waitlistPosition = await nextWaitlistPosition(eventId, client);
      await client.query(
        `INSERT INTO waitlist_entries (event_id, registration_id, position)
         VALUES ($1, $2, $3)`,
        [eventId, registration.id, waitlistPosition],
      );
    }

    const action =
      targetState === "Waitlisted"
        ? "registration.waitlisted"
        : "registration.accepted";

    await writeRegistrationAudit(
      {
        eventId,
        registrationId: registration.id,
        action,
        actorId: context.actorId,
        actorRole: context.actorRole,
        before: {},
        after: {
          registrationId: registration.id,
          participantId,
          state: targetState,
          waitlistPosition,
        },
      },
      client,
    );

    await client.query("COMMIT");

    return { ...registration, waitlistPosition };
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

async function promoteNextWaitlisted(
  eventId: string,
  context: ActorContext,
  client: PoolClient,
): Promise<RegistrationRow | null> {
  await lockEventRuleConfig(eventId, client);

  const capacityResult = await client.query(
    "SELECT capacity FROM event_rule_configs WHERE event_id = $1",
    [eventId],
  );
  const capacity = (capacityResult.rows[0] as { capacity: number }).capacity;
  const registeredCount = await countSeatHolders(eventId, client);

  if (registeredCount >= capacity) {
    return null;
  }

  const queueResult = await client.query(
    `SELECT w.*, r.state AS registration_state
     FROM waitlist_entries w
     INNER JOIN registrations r ON r.id = w.registration_id
     WHERE w.event_id = $1
       AND w.promoted_at IS NULL
       AND w.expired_at IS NULL
       AND r.state = 'Waitlisted'
     ORDER BY w.position ASC
     LIMIT 1
     FOR UPDATE OF w, r`,
    [eventId],
  );

  if (queueResult.rowCount === 0) {
    return null;
  }

  const entry = mapWaitlistEntry(queueResult.rows[0] as Record<string, unknown>);
  const beforeState = (queueResult.rows[0] as { registration_state: string })
    .registration_state;

  const updateResult = await client.query(
    `UPDATE registrations
     SET state = 'Registered',
         status_reason_code = NULL,
         status_reason_text = NULL,
         updated_at = NOW(),
         version = version + 1
     WHERE id = $1 AND state = 'Waitlisted'
     RETURNING *`,
    [entry.registrationId],
  );

  if (updateResult.rowCount === 0) {
    throw new ApiError({
      code: VALIDATION_ERROR_CODES.WAITLIST_ORDER_CONFLICT,
      message: "Waitlist promotion conflict; queue order changed.",
      statusCode: 409,
      details: { registrationId: entry.registrationId },
    });
  }

  await client.query(
    `UPDATE waitlist_entries
     SET promoted_at = NOW()
     WHERE id = $1`,
    [entry.id],
  );

  const promoted = mapRegistration(
    updateResult.rows[0] as Record<string, unknown>,
  );

  await writeRegistrationAudit(
    {
      eventId,
      registrationId: promoted.id,
      action: "registration.promoted_from_waitlist",
      actorId: context.actorId,
      actorRole: context.actorRole,
      before: { state: beforeState, waitlistPosition: entry.position },
      after: { state: promoted.state },
    },
    client,
  );

  return promoted;
}

export async function cancelRegistration(
  registration: RegistrationRow,
  cancelledState: "CancelledByUser" | "CancelledByOrganizer",
  context: ActorContext & { reasonCode?: string; reasonText?: string },
): Promise<{
  cancelled: RegistrationRow;
  promoted: RegistrationRow | null;
}> {
  const pool = getPool();
  const client = await pool.connect();

  try {
    await client.query("BEGIN");

    const locked = await client.query(
      "SELECT * FROM registrations WHERE id = $1 FOR UPDATE",
      [registration.id],
    );
    if (locked.rowCount === 0) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "Registration not found.",
        statusCode: 404,
        details: { registrationId: registration.id },
      });
    }

    const current = mapRegistration(locked.rows[0] as Record<string, unknown>);
    const fromState = current.state;
    const hadSeat = fromState === "Registered" || fromState === "CheckedIn";

    const updateResult = await client.query(
      `UPDATE registrations
       SET state = $1,
           cancelled_at = NOW(),
           status_reason_code = $2,
           status_reason_text = $3,
           updated_at = NOW(),
           version = version + 1
       WHERE id = $4
       RETURNING *`,
      [
        cancelledState,
        context.reasonCode ?? null,
        context.reasonText ?? null,
        registration.id,
      ],
    );

    const cancelled = mapRegistration(
      updateResult.rows[0] as Record<string, unknown>,
    );

    if (fromState === "Waitlisted") {
      await client.query(
        `UPDATE waitlist_entries
         SET expired_at = NOW()
         WHERE registration_id = $1
           AND promoted_at IS NULL
           AND expired_at IS NULL`,
        [registration.id],
      );
    }

    await writeRegistrationAudit(
      {
        eventId: registration.eventId,
        registrationId: registration.id,
        action: "registration.cancelled",
        actorId: context.actorId,
        actorRole: context.actorRole,
        reasonCode: context.reasonCode ?? null,
        reasonText: context.reasonText ?? null,
        before: { state: fromState },
        after: { state: cancelled.state },
      },
      client,
    );

    let promoted: RegistrationRow | null = null;
    if (hadSeat) {
      promoted = await promoteNextWaitlisted(
        registration.eventId,
        context,
        client,
      );
    }

    await client.query("COMMIT");
    return { cancelled, promoted };
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

export async function listRegistrationsForEvent(
  eventId: string,
  client: Pool | PoolClient = getPool(),
): Promise<RegistrationWithWaitlist[]> {
  const result = await client.query(
    `SELECT r.*, w.position AS waitlist_position
     FROM registrations r
     LEFT JOIN waitlist_entries w
       ON w.registration_id = r.id
       AND w.promoted_at IS NULL
       AND w.expired_at IS NULL
     WHERE r.event_id = $1
     ORDER BY r.requested_at ASC`,
    [eventId],
  );

  return result.rows.map((row) => {
    const registration = mapRegistration(row as Record<string, unknown>);
    const waitlistPosition =
      row.waitlist_position === null || row.waitlist_position === undefined
        ? null
        : Number(row.waitlist_position);
    return { ...registration, waitlistPosition };
  });
}

export async function listWaitlistForEvent(
  eventId: string,
  client: Pool | PoolClient = getPool(),
): Promise<
  Array<{
    waitlistEntryId: string;
    registrationId: string;
    participantId: string;
    position: number;
    enqueuedAt: string;
    state: RegistrationState;
  }>
> {
  const result = await client.query(
    `SELECT w.id, w.registration_id, w.position, w.enqueued_at,
            r.participant_id, r.state
     FROM waitlist_entries w
     INNER JOIN registrations r ON r.id = w.registration_id
     WHERE w.event_id = $1
       AND w.promoted_at IS NULL
       AND w.expired_at IS NULL
     ORDER BY w.position ASC`,
    [eventId],
  );

  return result.rows.map((row) => ({
    waitlistEntryId: row.id as string,
    registrationId: row.registration_id as string,
    participantId: row.participant_id as string,
    position: row.position as number,
    enqueuedAt: (row.enqueued_at as Date).toISOString(),
    state: row.state as RegistrationState,
  }));
}

export async function loadRegistrationWithWaitlist(
  registration: RegistrationRow,
): Promise<RegistrationWithWaitlist> {
  const waitlistPosition = await getWaitlistPosition(registration.id);
  return { ...registration, waitlistPosition };
}
