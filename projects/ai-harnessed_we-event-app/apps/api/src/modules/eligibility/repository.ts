import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  VALIDATION_ERROR_CODES,
  type CertificateEligibilityState,
} from "@we-event/domain";
import type { Pool, PoolClient } from "pg";
import { getPool } from "../../db/pool.js";
import { ApiError } from "../../errors/api-error.js";
import { insertAuditLog } from "../audit/repository.js";
import type { RegistrationRow } from "../registration/types.js";
import type {
  ActorContext,
  EligibilityAuditInput,
  EligibilityEvaluationResult,
  EligibilityRow,
} from "./types.js";
import { assertEvaluationHasReason } from "./validation.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

let schemaReady: Promise<void> | null = null;

export async function ensureEligibilitySchema(): Promise<void> {
  if (!schemaReady) {
    schemaReady = (async () => {
      const sql = await readFile(join(__dirname, "schema.sql"), "utf8");
      await getPool().query(sql);
    })();
  }
  await schemaReady;
}

function mapEligibility(row: Record<string, unknown>): EligibilityRow {
  return {
    id: row.id as string,
    eventId: row.event_id as string,
    registrationId: row.registration_id as string,
    participantId: row.participant_id as string,
    result: row.result as CertificateEligibilityState,
    reasonCode: (row.reason_code as string | null) ?? null,
    reasonText: (row.reason_text as string | null) ?? null,
    evaluatedAt: row.evaluated_at
      ? (row.evaluated_at as Date).toISOString()
      : null,
    overriddenBy: (row.overridden_by as string | null) ?? null,
    createdAt: (row.created_at as Date).toISOString(),
    updatedAt: (row.updated_at as Date).toISOString(),
    version: row.version as number,
  };
}

async function writeEligibilityAudit(
  input: EligibilityAuditInput,
  client: Pool | PoolClient,
): Promise<void> {
  await insertAuditLog(
    {
      eventId: input.eventId,
      entityType: "CertificateEligibility",
      entityId: input.eligibilityId,
      action: input.action,
      actorId: input.actorId,
      actorRole: input.actorRole,
      reasonCode: input.reasonCode,
      reasonText: input.reasonText,
      before: input.before,
      after: input.after,
    },
    client,
  );
}

export async function findEligibilityByRegistrationId(
  registrationId: string,
  client: Pool | PoolClient = getPool(),
): Promise<EligibilityRow | null> {
  const result = await client.query(
    "SELECT * FROM certificate_eligibilities WHERE registration_id = $1",
    [registrationId],
  );
  if (result.rowCount === 0) {
    return null;
  }
  return mapEligibility(result.rows[0] as Record<string, unknown>);
}

const ELIGIBILITY_REGISTRATION_STATES = [
  "Attended",
  "Absent",
  "CheckedIn",
  "Registered",
] as const;

function mapRegistrationRow(row: Record<string, unknown>): RegistrationRow {
  return {
    id: row.id as string,
    eventId: row.event_id as string,
    participantId: row.participant_id as string,
    state: row.state as RegistrationRow["state"],
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

export interface ListEligibilityRegistrationsOptions {
  eligibility?: CertificateEligibilityState;
  sortColumn: string;
  sortDirection: "ASC" | "DESC";
  limit: number;
  offset: number;
}

export interface ListEligibilityRegistrationsResult {
  items: RegistrationRow[];
  total: number;
}

export async function listRegistrationsForEligibilityPaginated(
  eventId: string,
  options: ListEligibilityRegistrationsOptions,
  client: Pool | PoolClient = getPool(),
): Promise<ListEligibilityRegistrationsResult> {
  const params: unknown[] = [eventId, ELIGIBILITY_REGISTRATION_STATES];
  const conditions = [
    "r.event_id = $1",
    "r.state = ANY($2::text[])",
  ];
  let paramIndex = 3;

  if (options.eligibility) {
    conditions.push(
      `COALESCE(ce.result, 'PendingEvaluation') = $${paramIndex++}`,
    );
    params.push(options.eligibility);
  }

  const where = `WHERE ${conditions.join(" AND ")}`;
  const join = `LEFT JOIN certificate_eligibilities ce ON ce.registration_id = r.id`;

  const countResult = await client.query(
    `SELECT COUNT(*)::int AS total
     FROM registrations r
     ${join}
     ${where}`,
    params,
  );
  const total = (countResult.rows[0] as { total: number }).total;

  const listParams = [...params, options.limit, options.offset];
  const result = await client.query(
    `SELECT r.*
     FROM registrations r
     ${join}
     ${where}
     ORDER BY ${options.sortColumn} ${options.sortDirection}
     LIMIT $${paramIndex++} OFFSET $${paramIndex}`,
    listParams,
  );

  return {
    items: result.rows.map((row) =>
      mapRegistrationRow(row as Record<string, unknown>),
    ),
    total,
  };
}

export async function listRegistrationsForEligibilityExport(
  eventId: string,
  options: Pick<ListEligibilityRegistrationsOptions, "eligibility" | "sortColumn" | "sortDirection">,
  client: Pool | PoolClient = getPool(),
): Promise<RegistrationRow[]> {
  const params: unknown[] = [eventId, ELIGIBILITY_REGISTRATION_STATES];
  const conditions = ["r.event_id = $1", "r.state = ANY($2::text[])"];
  let paramIndex = 3;

  if (options.eligibility) {
    conditions.push(
      `COALESCE(ce.result, 'PendingEvaluation') = $${paramIndex++}`,
    );
    params.push(options.eligibility);
  }

  const where = `WHERE ${conditions.join(" AND ")}`;
  const join = `LEFT JOIN certificate_eligibilities ce ON ce.registration_id = r.id`;

  const result = await client.query(
    `SELECT r.*
     FROM registrations r
     ${join}
     ${where}
     ORDER BY ${options.sortColumn} ${options.sortDirection}`,
    params,
  );

  return result.rows.map((row) =>
    mapRegistrationRow(row as Record<string, unknown>),
  );
}

export async function listEligibilitiesForEvent(
  eventId: string,
  client: Pool | PoolClient = getPool(),
): Promise<EligibilityRow[]> {
  const result = await client.query(
    `SELECT * FROM certificate_eligibilities
     WHERE event_id = $1
     ORDER BY evaluated_at DESC NULLS LAST, created_at ASC`,
    [eventId],
  );
  return result.rows.map((row) =>
    mapEligibility(row as Record<string, unknown>),
  );
}

export async function persistEligibilityEvaluation(
  registration: RegistrationRow,
  evaluation: EligibilityEvaluationResult,
  context: ActorContext,
): Promise<EligibilityRow> {
  assertEvaluationHasReason(evaluation);

  const pool = getPool();
  const client = await pool.connect();

  try {
    await client.query("BEGIN");

    const existing = await findEligibilityByRegistrationId(
      registration.id,
      client,
    );

    if (existing?.result === "Revoked") {
      await client.query("COMMIT");
      return existing;
    }

    const before = existing
      ? {
          result: existing.result,
          reasonCode: existing.reasonCode,
          reasonText: existing.reasonText,
        }
      : { result: "PendingEvaluation" };

    let row: EligibilityRow;

    if (existing) {
      const updateResult = await client.query(
        `UPDATE certificate_eligibilities
         SET result = $1,
             reason_code = $2,
             reason_text = $3,
             evaluated_at = NOW(),
             updated_at = NOW(),
             version = version + 1
         WHERE registration_id = $4
           AND result != 'Revoked'
         RETURNING *`,
        [
          evaluation.result,
          evaluation.reasonCode,
          evaluation.reasonText,
          registration.id,
        ],
      );

      if (updateResult.rowCount === 0) {
        await client.query("COMMIT");
        return existing;
      }

      row = mapEligibility(updateResult.rows[0] as Record<string, unknown>);
    } else {
      const insertResult = await client.query(
        `INSERT INTO certificate_eligibilities (
           event_id, registration_id, participant_id,
           result, reason_code, reason_text, evaluated_at
         ) VALUES ($1, $2, $3, $4, $5, $6, NOW())
         RETURNING *`,
        [
          registration.eventId,
          registration.id,
          registration.participantId,
          evaluation.result,
          evaluation.reasonCode,
          evaluation.reasonText,
        ],
      );

      row = mapEligibility(insertResult.rows[0] as Record<string, unknown>);
    }

    await writeEligibilityAudit(
      {
        eventId: registration.eventId,
        eligibilityId: row.id,
        registrationId: registration.id,
        action: "eligibility.evaluated",
        actorId: context.actorId,
        actorRole: context.actorRole,
        before,
        after: {
          result: row.result,
          reasonCode: row.reasonCode,
          reasonText: row.reasonText,
          evaluatedAt: row.evaluatedAt,
        },
      },
      client,
    );

    await client.query("COMMIT");
    return row;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

export async function revokeEligibility(
  registration: RegistrationRow,
  reasonCode: string,
  reasonText: string,
  context: ActorContext,
): Promise<EligibilityRow> {
  const pool = getPool();
  const client = await pool.connect();

  try {
    await client.query("BEGIN");

    const existing = await findEligibilityByRegistrationId(
      registration.id,
      client,
    );

    if (!existing) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "Eligibility record not found.",
        statusCode: 404,
        details: { registrationId: registration.id },
      });
    }

    if (existing.result !== "Eligible") {
      throw new ApiError({
        code: VALIDATION_ERROR_CODES.ELIGIBILITY_OVERRIDE_FORBIDDEN,
        message: "Only eligible participants may be revoked.",
        statusCode: 409,
        details: { currentResult: existing.result },
      });
    }

    const updateResult = await client.query(
      `UPDATE certificate_eligibilities
       SET result = 'Revoked',
           reason_code = $1,
           reason_text = $2,
           overridden_by = $3,
           evaluated_at = NOW(),
           updated_at = NOW(),
           version = version + 1
       WHERE registration_id = $4 AND result = 'Eligible'
       RETURNING *`,
      [reasonCode, reasonText, context.actorId, registration.id],
    );

    if (updateResult.rowCount === 0) {
      throw new ApiError({
        code: VALIDATION_ERROR_CODES.ELIGIBILITY_OVERRIDE_FORBIDDEN,
        message: "Eligibility could not be revoked.",
        statusCode: 409,
      });
    }

    const row = mapEligibility(updateResult.rows[0] as Record<string, unknown>);

    await writeEligibilityAudit(
      {
        eventId: registration.eventId,
        eligibilityId: row.id,
        registrationId: registration.id,
        action: "eligibility.revoked",
        actorId: context.actorId,
        actorRole: context.actorRole,
        reasonCode,
        reasonText,
        before: {
          result: existing.result,
          reasonCode: existing.reasonCode,
          reasonText: existing.reasonText,
        },
        after: {
          result: row.result,
          reasonCode: row.reasonCode,
          reasonText: row.reasonText,
          overriddenBy: row.overriddenBy,
        },
      },
      client,
    );

    await client.query("COMMIT");
    return row;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}
