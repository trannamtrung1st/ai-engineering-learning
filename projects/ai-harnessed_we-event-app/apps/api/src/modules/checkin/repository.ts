import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  VALIDATION_ERROR_CODES,
  type RegistrationState,
} from "@we-event/domain";
import type { Pool, PoolClient } from "pg";
import { getPool } from "../../db/pool.js";
import { ApiError } from "../../errors/api-error.js";
import { insertAuditLog } from "../audit/repository.js";
import type { RegistrationRow } from "../registration/types.js";
import type {
  ActorContext,
  AttendanceEntry,
  CheckinAuditInput,
  CheckinMethod,
  CheckinRecordRow,
  ListAttendanceOptions,
  ListAttendanceResult,
} from "./types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

let schemaReady: Promise<void> | null = null;

export async function ensureCheckinSchema(): Promise<void> {
  if (!schemaReady) {
    schemaReady = (async () => {
      const sql = await readFile(join(__dirname, "schema.sql"), "utf8");
      await getPool().query(sql);
    })();
  }
  await schemaReady;
}

function mapCheckinRecord(row: Record<string, unknown>): CheckinRecordRow {
  return {
    id: row.id as string,
    registrationId: row.registration_id as string,
    eventId: row.event_id as string,
    checkinAt: (row.checkin_at as Date).toISOString(),
    method: row.method as CheckinMethod,
    operatorId: (row.operator_id as string | null) ?? null,
    createdAt: (
      (row.created_at as Date | undefined) ??
      (row.checkin_at as Date)
    ).toISOString(),
  };
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

async function writeCheckinAudit(
  input: CheckinAuditInput,
  client: Pool | PoolClient,
): Promise<void> {
  await insertAuditLog(
    {
      eventId: input.eventId,
      entityType: "CheckinRecord",
      entityId: input.checkinId,
      action: input.action,
      actorId: input.actorId,
      actorRole: input.actorRole,
      before: input.before,
      after: input.after,
    },
    client,
  );
}

function isUniqueViolation(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code: string }).code === "23505"
  );
}

export async function findCheckinByRegistrationId(
  registrationId: string,
  client: Pool | PoolClient = getPool(),
): Promise<CheckinRecordRow | null> {
  const result = await client.query(
    "SELECT * FROM checkin_records WHERE registration_id = $1",
    [registrationId],
  );
  if (result.rowCount === 0) {
    return null;
  }
  return mapCheckinRecord(result.rows[0] as Record<string, unknown>);
}

export async function recordCheckin(
  registration: RegistrationRow,
  method: CheckinMethod,
  context: ActorContext,
  operatorId: string | null,
): Promise<{ record: CheckinRecordRow; registration: RegistrationRow }> {
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
    if (current.state !== "Registered") {
      if (current.state === "CheckedIn") {
        throw new ApiError({
          code: VALIDATION_ERROR_CODES.CHECKIN_ALREADY_RECORDED,
          message: "This registration is already checked in.",
          statusCode: 409,
          details: { registrationId: current.id, state: current.state },
        });
      }
      throw new ApiError({
        code: "INVALID_STATE_TRANSITION",
        message: "Only registered participants can check in.",
        statusCode: 409,
        details: { registrationId: current.id, state: current.state },
      });
    }

    const existing = await findCheckinByRegistrationId(registration.id, client);
    if (existing) {
      throw new ApiError({
        code: VALIDATION_ERROR_CODES.CHECKIN_ALREADY_RECORDED,
        message: "A valid check-in already exists for this registration.",
        statusCode: 409,
        details: {
          checkinId: existing.id,
          checkinAt: existing.checkinAt,
        },
      });
    }

    let insertResult;
    try {
      insertResult = await client.query(
        `INSERT INTO checkin_records (registration_id, event_id, checkin_at, method, operator_id)
         VALUES ($1, $2, NOW(), $3, $4)
         RETURNING *`,
        [registration.id, registration.eventId, method, operatorId],
      );
    } catch (error) {
      if (isUniqueViolation(error)) {
        throw new ApiError({
          code: VALIDATION_ERROR_CODES.CHECKIN_ALREADY_RECORDED,
          message: "A valid check-in already exists for this registration.",
          statusCode: 409,
        });
      }
      throw error;
    }

    const record = mapCheckinRecord(
      insertResult.rows[0] as Record<string, unknown>,
    );

    const updateResult = await client.query(
      `UPDATE registrations
       SET state = 'CheckedIn',
           updated_at = NOW(),
           version = version + 1
       WHERE id = $1 AND state = 'Registered'
       RETURNING *`,
      [registration.id],
    );

    if (updateResult.rowCount === 0) {
      throw new ApiError({
        code: "INVALID_STATE_TRANSITION",
        message: "Registration state changed during check-in.",
        statusCode: 409,
        details: { registrationId: registration.id },
      });
    }

    const updatedRegistration = mapRegistration(
      updateResult.rows[0] as Record<string, unknown>,
    );

    await writeCheckinAudit(
      {
        eventId: registration.eventId,
        registrationId: registration.id,
        checkinId: record.id,
        action: "checkin.recorded",
        actorId: context.actorId,
        actorRole: context.actorRole,
        before: { state: current.state },
        after: {
          state: updatedRegistration.state,
          checkinId: record.id,
          checkinAt: record.checkinAt,
          method: record.method,
        },
      },
      client,
    );

    await client.query("COMMIT");
    return { record, registration: updatedRegistration };
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

export async function finalizeAttendanceForEvent(
  eventId: string,
  context: ActorContext,
): Promise<{
  attendedCount: number;
  absentCount: number;
}> {
  const pool = getPool();
  const client = await pool.connect();

  try {
    await client.query("BEGIN");

    const checkedInResult = await client.query(
      `SELECT r.*
       FROM registrations r
       WHERE r.event_id = $1 AND r.state = 'CheckedIn'
       FOR UPDATE`,
      [eventId],
    );

    for (const row of checkedInResult.rows) {
      const registration = mapRegistration(row as Record<string, unknown>);
      const checkin = await findCheckinByRegistrationId(registration.id, client);
      if (!checkin) {
        throw new ApiError({
          code: "INTERNAL_ERROR",
          message:
            "Checked-in registration is missing a check-in record (BR-12).",
          statusCode: 500,
          details: { registrationId: registration.id },
        });
      }
    }

    const attendedResult = await client.query(
      `UPDATE registrations
       SET state = 'Attended',
           updated_at = NOW(),
           version = version + 1
       WHERE event_id = $1 AND state = 'CheckedIn'
       RETURNING id, participant_id`,
      [eventId],
    );

    for (const row of attendedResult.rows) {
      await insertAuditLog(
        {
          eventId,
          entityType: "Registration",
          entityId: row.id as string,
          action: "attendance.marked_attended",
          actorId: context.actorId,
          actorRole: context.actorRole,
          before: { state: "CheckedIn" },
          after: { state: "Attended" },
        },
        client,
      );
    }

    const absentResult = await client.query(
      `UPDATE registrations
       SET state = 'Absent',
           updated_at = NOW(),
           version = version + 1
       WHERE event_id = $1 AND state = 'Registered'
       RETURNING id, participant_id`,
      [eventId],
    );

    for (const row of absentResult.rows) {
      await insertAuditLog(
        {
          eventId,
          entityType: "Registration",
          entityId: row.id as string,
          action: "attendance.marked_absent",
          actorId: context.actorId,
          actorRole: context.actorRole,
          before: { state: "Registered" },
          after: { state: "Absent" },
        },
        client,
      );
    }

    await client.query("COMMIT");

    return {
      attendedCount: attendedResult.rowCount ?? 0,
      absentCount: absentResult.rowCount ?? 0,
    };
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

const ATTENDANCE_BASE_FROM = `FROM registrations r
     LEFT JOIN checkin_records c ON c.registration_id = r.id`;

const ATTENDANCE_BASE_WHERE = `WHERE r.event_id = $1
       AND r.state IN ('Registered', 'CheckedIn', 'Attended', 'Absent')`;

function mapAttendanceRow(row: Record<string, unknown>): AttendanceEntry {
  return {
    registrationId: row.registration_id as string,
    participantId: row.participant_id as string,
    state: row.state as string,
    checkinAt: row.checkin_at
      ? (row.checkin_at as Date).toISOString()
      : null,
    checkinMethod: (row.checkin_method as CheckinMethod | null) ?? null,
  };
}

export async function listAttendanceForEvent(
  eventId: string,
  options: ListAttendanceOptions,
  client: Pool | PoolClient = getPool(),
): Promise<ListAttendanceResult> {
  const nullsOrder =
    options.sortDirection === "DESC" ? "NULLS LAST" : "NULLS FIRST";

  const countResult = await client.query(
    `SELECT COUNT(*)::int AS total
     ${ATTENDANCE_BASE_FROM}
     ${ATTENDANCE_BASE_WHERE}`,
    [eventId],
  );
  const total = (countResult.rows[0] as { total: number }).total;

  const result = await client.query(
    `SELECT r.id AS registration_id,
            r.participant_id,
            r.state,
            c.checkin_at,
            c.method AS checkin_method
     ${ATTENDANCE_BASE_FROM}
     ${ATTENDANCE_BASE_WHERE}
     ORDER BY ${options.sortColumn} ${options.sortDirection} ${nullsOrder}
     LIMIT $2 OFFSET $3`,
    [eventId, options.limit, options.offset],
  );

  return {
    items: result.rows.map((row) =>
      mapAttendanceRow(row as Record<string, unknown>),
    ),
    total,
  };
}
