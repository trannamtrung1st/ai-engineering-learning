import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";
import type { Pool, PoolClient } from "pg";
import { getPool } from "../../db/pool.js";
import { ApiError } from "../../errors/api-error.js";
import { insertAuditLog } from "../audit/repository.js";
import type { RegistrationRow } from "../registration/types.js";
import type {
  ActorContext,
  FeedbackAuditInput,
  FeedbackRow,
} from "./types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

let schemaReady: Promise<void> | null = null;

export async function ensureFeedbackSchema(): Promise<void> {
  if (!schemaReady) {
    schemaReady = (async () => {
      const sql = await readFile(join(__dirname, "schema.sql"), "utf8");
      await getPool().query(sql);
    })();
  }
  await schemaReady;
}

function mapFeedback(row: Record<string, unknown>): FeedbackRow {
  return {
    id: row.id as string,
    eventId: row.event_id as string,
    registrationId: row.registration_id as string,
    participantId: row.participant_id as string,
    submittedAt: (row.submitted_at as Date).toISOString(),
    payload: row.payload_json as Record<string, unknown>,
    createdAt: (
      (row.created_at as Date | undefined) ??
      (row.submitted_at as Date)
    ).toISOString(),
    updatedAt: (
      (row.updated_at as Date | undefined) ??
      (row.submitted_at as Date)
    ).toISOString(),
  };
}

async function writeFeedbackAudit(
  input: FeedbackAuditInput,
  client: Pool | PoolClient,
): Promise<void> {
  await insertAuditLog(
    {
      eventId: input.eventId,
      entityType: "Feedback",
      entityId: input.feedbackId,
      action: input.action,
      actorId: input.actorId,
      actorRole: input.actorRole,
      before: input.before,
      after: input.after,
    },
    client,
  );
}

export async function findFeedbackByRegistrationId(
  registrationId: string,
  client: Pool | PoolClient = getPool(),
): Promise<FeedbackRow | null> {
  const result = await client.query(
    "SELECT * FROM feedback_submissions WHERE registration_id = $1",
    [registrationId],
  );
  if (result.rowCount === 0) {
    return null;
  }
  return mapFeedback(result.rows[0] as Record<string, unknown>);
}

export async function findFeedbackByParticipant(
  eventId: string,
  participantId: string,
  client: Pool | PoolClient = getPool(),
): Promise<FeedbackRow | null> {
  const result = await client.query(
    `SELECT * FROM feedback_submissions
     WHERE event_id = $1 AND participant_id = $2`,
    [eventId, participantId],
  );
  if (result.rowCount === 0) {
    return null;
  }
  return mapFeedback(result.rows[0] as Record<string, unknown>);
}

export async function submitOrUpdateFeedback(
  registration: RegistrationRow,
  answers: Record<string, unknown>,
  context: ActorContext,
  existing: FeedbackRow | null,
): Promise<FeedbackRow> {
  const pool = getPool();
  const client = await pool.connect();

  try {
    await client.query("BEGIN");

    let row: FeedbackRow;

    if (existing) {
      const updateResult = await client.query(
        `UPDATE feedback_submissions
         SET payload_json = $1,
             submitted_at = NOW(),
             updated_at = NOW()
         WHERE registration_id = $2
         RETURNING *`,
        [JSON.stringify(answers), registration.id],
      );

      if (updateResult.rowCount === 0) {
        throw new ApiError({
          code: "NOT_FOUND",
          message: "Feedback record not found for update.",
          statusCode: 404,
        });
      }

      row = mapFeedback(updateResult.rows[0] as Record<string, unknown>);

      await writeFeedbackAudit(
        {
          eventId: registration.eventId,
          registrationId: registration.id,
          feedbackId: row.id,
          action: "feedback.updated",
          actorId: context.actorId,
          actorRole: context.actorRole,
          before: { payload: existing.payload, submittedAt: existing.submittedAt },
          after: { payload: row.payload, submittedAt: row.submittedAt },
        },
        client,
      );
    } else {
      let insertResult;
      try {
        insertResult = await client.query(
          `INSERT INTO feedback_submissions (
             event_id, registration_id, participant_id, payload_json
           ) VALUES ($1, $2, $3, $4)
           RETURNING *`,
          [
            registration.eventId,
            registration.id,
            registration.participantId,
            JSON.stringify(answers),
          ],
        );
      } catch (error) {
        if (
          typeof error === "object" &&
          error !== null &&
          "code" in error &&
          (error as { code: string }).code === "23505"
        ) {
          throw new ApiError({
            code: VALIDATION_ERROR_CODES.FEEDBACK_DUPLICATE,
            message: "Official feedback has already been submitted for this event.",
            statusCode: 409,
          });
        }
        throw error;
      }

      row = mapFeedback(insertResult.rows[0] as Record<string, unknown>);

      await writeFeedbackAudit(
        {
          eventId: registration.eventId,
          registrationId: registration.id,
          feedbackId: row.id,
          action: "feedback.submitted",
          actorId: context.actorId,
          actorRole: context.actorRole,
          before: {},
          after: {
            feedbackId: row.id,
            submittedAt: row.submittedAt,
          },
        },
        client,
      );
    }

    await client.query("COMMIT");
    return row;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}
