import { randomUUID } from "node:crypto";
import type pg from "pg";
import { isStudentEnrolled } from "../academic-structure/validation.js";
import { getOrRotateCurrentQr, issueQrToken, resolveQrToken } from "./qr-service.js";
import {
  evaluateCheckInFailure,
  haversineMeters,
  resolveAttendanceStatus,
} from "./validation.js";
import type {
  CheckInCommandResult,
  CheckInOutcome,
  CheckInSuccessResult,
  CurrentQrResult,
  EffectivePolicy,
  GpsPayload,
  SessionContext,
} from "./types.js";

type IdempotencyRecord = {
  statusCode: number;
  body: CheckInSuccessResult | { outcome: string; classSessionId?: string };
};

const DEFAULT_POLICY: EffectivePolicy = {
  presentWindowMinutes: 15,
  lateWindowMinutes: 15,
  gpsRequired: false,
  gpsRadiusMeters: 100,
  gpsMinAccuracyMeters: null,
};

export function createCheckInRepository(pool: pg.Pool) {
  const idempotencyCache = new Map<string, IdempotencyRecord>();

  async function loadSession(client: pg.PoolClient, sessionId: string): Promise<SessionContext | null> {
    const result = await client.query<{
      id: string;
      class_section_id: string;
      state: SessionContext["state"];
      opened_at: Date | null;
    }>(
      `
      SELECT id, class_section_id, state, opened_at
      FROM class_sessions
      WHERE id = $1
      `,
      [sessionId],
    );
    const row = result.rows[0];
    if (!row) return null;
    return {
      id: row.id,
      classSectionId: row.class_section_id,
      state: row.state,
      openedAt: row.opened_at?.toISOString() ?? null,
    };
  }

  async function loadEffectivePolicy(
    client: pg.PoolClient,
    _classSectionId: string,
  ): Promise<EffectivePolicy> {
    const result = await client.query<{
      present_window_minutes: number;
      late_window_minutes: number;
      gps_required: boolean;
      gps_radius_meters: number | null;
      gps_min_accuracy_meters: number | null;
    }>(
      `
      SELECT present_window_minutes, late_window_minutes, gps_required,
             gps_radius_meters, gps_min_accuracy_meters
      FROM attendance_policies
      WHERE is_active = true
      ORDER BY
        CASE scope_type
          WHEN 'ClassSection' THEN 1
          WHEN 'Course' THEN 2
          WHEN 'Faculty' THEN 3
          WHEN 'Institution' THEN 4
        END
      LIMIT 1
      `,
      [],
    );
    const row = result.rows[0];
    if (!row) return DEFAULT_POLICY;
    return {
      presentWindowMinutes: row.present_window_minutes,
      lateWindowMinutes: row.late_window_minutes,
      gpsRequired: row.gps_required,
      gpsRadiusMeters: row.gps_radius_meters,
      gpsMinAccuracyMeters: row.gps_min_accuracy_meters,
    };
  }

  async function loadRoomCoordinates(
    client: pg.PoolClient,
    sessionId: string,
  ): Promise<{ latitude: number; longitude: number } | null> {
    const result = await client.query<{ latitude: string | null; longitude: string | null }>(
      `
      SELECT r.latitude, r.longitude
      FROM class_sessions cs
      JOIN rooms r ON r.id = cs.room_id
      WHERE cs.id = $1
      `,
      [sessionId],
    );
    const row = result.rows[0];
    if (!row?.latitude || !row?.longitude) return null;
    return { latitude: Number(row.latitude), longitude: Number(row.longitude) };
  }

  async function loadExistingAttendance(
    client: pg.PoolClient,
    sessionId: string,
    studentUserId: string,
  ): Promise<string | null> {
    const result = await client.query<{ status: string }>(
      `
      SELECT status FROM attendance_records
      WHERE class_session_id = $1 AND student_user_id = $2
      `,
      [sessionId, studentUserId],
    );
    return result.rows[0]?.status ?? null;
  }

  async function persistAttempt(
    client: pg.PoolClient,
    params: {
      attemptId: string;
      classSessionId: string;
      studentUserId: string;
      qrSessionTokenId: string | null;
      outcome: string;
      clientTimestamp?: string;
      gps?: GpsPayload | null;
      distanceFromRoomMeters?: number | null;
      gpsValidationResult?: string | null;
      deviceUserAgent?: string | null;
      correlationId?: string | null;
    },
  ): Promise<void> {
    await client.query(
      `
      INSERT INTO check_in_attempts (
        id, class_session_id, student_user_id, qr_session_token_id, outcome,
        submitted_at, client_timestamp, gps_latitude, gps_longitude,
        gps_accuracy_meters, distance_from_room_meters, gps_validation_result,
        device_user_agent, correlation_id
      )
      VALUES ($1, $2, $3, $4, $5, now(), $6, $7, $8, $9, $10, $11, $12, $13)
      `,
      [
        params.attemptId,
        params.classSessionId,
        params.studentUserId,
        params.qrSessionTokenId,
        params.outcome,
        params.clientTimestamp ?? null,
        params.gps?.latitude ?? null,
        params.gps?.longitude ?? null,
        params.gps?.accuracyMeters ?? null,
        params.distanceFromRoomMeters ?? null,
        params.gpsValidationResult ?? null,
        params.deviceUserAgent ?? null,
        params.correlationId ?? null,
      ],
    );
  }

  return {
    async getCurrentQr(sessionId: string): Promise<
      | { ok: true; result: CurrentQrResult }
      | { ok: false; code: "SessionNotFound" | "SessionNotOpen" | "SessionClosed" }
    > {
      const client = await pool.connect();
      try {
        await client.query("BEGIN");
        const session = await loadSession(client, sessionId);
        if (!session) {
          await client.query("ROLLBACK");
          return { ok: false, code: "SessionNotFound" };
        }
        if (session.state === "Scheduled" || session.state === "Cancelled") {
          await client.query("ROLLBACK");
          return { ok: false, code: "SessionNotOpen" };
        }
        if (session.state === "Closed") {
          await client.query("ROLLBACK");
          return { ok: false, code: "SessionClosed" };
        }

        const result = await getOrRotateCurrentQr(client, sessionId);
        await client.query("COMMIT");
        return { ok: true, result };
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      } finally {
        client.release();
      }
    },

    async submitCheckIn(params: {
      studentUserId: string;
      qrToken: string;
      clientTimestamp?: string;
      gps?: GpsPayload | null;
      deviceUserAgent?: string | null;
      correlationId?: string | null;
      idempotencyKey?: string;
    }): Promise<{ statusCode: number; result: CheckInCommandResult }> {
      const cacheKey = params.idempotencyKey
        ? `checkin:${params.studentUserId}:${params.qrToken}:${params.idempotencyKey}`
        : null;

      if (cacheKey) {
        const cached = idempotencyCache.get(cacheKey);
        if (cached) {
          return {
            statusCode: cached.statusCode,
            result: cached.body as CheckInCommandResult,
          };
        }
      }

      const client = await pool.connect();
      try {
        await client.query("BEGIN");

        const resolved = await resolveQrToken(client, params.qrToken);
        const sessionId = resolved?.classSessionId ?? null;
        const session = sessionId ? await loadSession(client, sessionId) : null;
        const classSectionId = session?.classSectionId ?? null;

        const tokenExpired =
          !resolved ||
          resolved.state === "Expired" ||
          new Date(resolved.expiresAt).getTime() <= Date.now();

        const enrolled =
          classSectionId !== null
            ? await isStudentEnrolled(client.query.bind(client), params.studentUserId, classSectionId)
            : false;

        const existingStatus =
          sessionId !== null
            ? await loadExistingAttendance(client, sessionId, params.studentUserId)
            : null;

        const policy =
          classSectionId !== null
            ? await loadEffectivePolicy(client, classSectionId)
            : DEFAULT_POLICY;

        let gpsFailure: Exclude<CheckInOutcome, "Success"> | null = null;
        let distanceFromRoom: number | null = null;
        let gpsValidationResult: string | null = null;

        if (session?.state === "Open" && resolved && !tokenExpired && enrolled) {
          if (policy.gpsRequired) {
            if (!params.gps) {
              gpsFailure = "GpsRequired";
            } else {
              const baseFailure = evaluateCheckInFailure({
                sessionState: session.state,
                tokenFound: true,
                tokenExpired: false,
                enrolled: true,
                existingAttendanceStatus: existingStatus,
                policy,
                gps: params.gps,
              });
              if (baseFailure && baseFailure !== "DuplicateCheckIn") {
                gpsFailure = baseFailure;
              } else {
                const room = await loadRoomCoordinates(client, session.id);
                if (room && policy.gpsRadiusMeters !== null) {
                  distanceFromRoom = haversineMeters(
                    params.gps.latitude,
                    params.gps.longitude,
                    room.latitude,
                    room.longitude,
                  );
                  if (distanceFromRoom > policy.gpsRadiusMeters) {
                    gpsFailure = "OutOfRadius";
                    gpsValidationResult = "Fail";
                  } else {
                    gpsValidationResult = "Pass";
                  }
                }
              }
            }
          }
        }

        const failureOutcome =
          gpsFailure ??
          (resolved === null
            ? "InvalidQr"
            : evaluateCheckInFailure({
                sessionState: session!.state,
                tokenFound: true,
                tokenExpired,
                enrolled,
                existingAttendanceStatus: existingStatus,
                policy,
                gps: params.gps,
              }));

        const attemptId = randomUUID();

        if (failureOutcome) {
          if (sessionId) {
            await persistAttempt(client, {
              attemptId,
              classSessionId: sessionId,
              studentUserId: params.studentUserId,
              qrSessionTokenId: resolved?.id ?? null,
              outcome: failureOutcome,
              clientTimestamp: params.clientTimestamp,
              gps: params.gps,
              distanceFromRoomMeters: distanceFromRoom,
              gpsValidationResult,
              deviceUserAgent: params.deviceUserAgent,
              correlationId: params.correlationId,
            });
          }
          await client.query("COMMIT");

          const failureResult: CheckInCommandResult = {
            outcome: failureOutcome,
            classSessionId: sessionId ?? undefined,
            ...(failureOutcome === "OutOfRadius" && distanceFromRoom !== null
              ? {
                  details: {
                    distanceMeters: distanceFromRoom,
                    allowedRadiusMeters: policy.gpsRadiusMeters,
                  },
                }
              : {}),
          };

          const statusCode = failureOutcome === "DuplicateCheckIn" ? 409 : 422;
          if (cacheKey) {
            idempotencyCache.set(cacheKey, { statusCode, body: failureResult });
          }
          return { statusCode, result: failureResult };
        }

        const checkInAt = new Date();
        const attendanceStatus = resolveAttendanceStatus(
          session!.openedAt!,
          checkInAt,
          policy,
        );

        await client.query(`SELECT pg_advisory_xact_lock(hashtext($1))`, [
          `${session!.id}:${params.studentUserId}`,
        ]);

        const recheckStatus = await loadExistingAttendance(client, session!.id, params.studentUserId);
        if (recheckStatus && evaluateCheckInFailure({
          sessionState: session!.state,
          tokenFound: true,
          tokenExpired: false,
          enrolled: true,
          existingAttendanceStatus: recheckStatus,
          policy,
          gps: params.gps,
        }) === "DuplicateCheckIn") {
          await persistAttempt(client, {
            attemptId,
            classSessionId: session!.id,
            studentUserId: params.studentUserId,
            qrSessionTokenId: resolved!.id,
            outcome: "DuplicateCheckIn",
            clientTimestamp: params.clientTimestamp,
            deviceUserAgent: params.deviceUserAgent,
            correlationId: params.correlationId,
          });
          await client.query("COMMIT");
          const dupResult: CheckInCommandResult = {
            outcome: "DuplicateCheckIn",
            classSessionId: session!.id,
          };
          if (cacheKey) {
            idempotencyCache.set(cacheKey, { statusCode: 409, body: dupResult });
          }
          return { statusCode: 409, result: dupResult };
        }

        await persistAttempt(client, {
          attemptId,
          classSessionId: session!.id,
          studentUserId: params.studentUserId,
          qrSessionTokenId: resolved!.id,
          outcome: "Success",
          clientTimestamp: params.clientTimestamp,
          gps: params.gps,
          distanceFromRoomMeters: distanceFromRoom,
          gpsValidationResult: gpsValidationResult ?? (params.gps ? "Skipped" : null),
          deviceUserAgent: params.deviceUserAgent,
          correlationId: params.correlationId,
        });

        const insertResult = await client.query<{ check_in_at: Date }>(
          `
          INSERT INTO attendance_records (
            id, class_session_id, class_section_id, student_user_id, status,
            check_in_method, check_in_at, last_modified_by_user_id, source_attempt_id
          )
          VALUES ($1, $2, $3, $4, $5, 'QR', $6, $4, $7)
          RETURNING check_in_at
          `,
          [
            randomUUID(),
            session!.id,
            session!.classSectionId,
            params.studentUserId,
            attendanceStatus,
            checkInAt.toISOString(),
            attemptId,
          ],
        );

        const checkInAtIso = insertResult.rows[0]!.check_in_at.toISOString();

        await client.query("COMMIT");

        const successResult: CheckInSuccessResult = {
          outcome: "Success",
          attendanceStatus,
          classSessionId: session!.id,
          checkInAt: checkInAtIso,
        };

        if (cacheKey) {
          idempotencyCache.set(cacheKey, { statusCode: 200, body: successResult });
        }
        return { statusCode: 200, result: successResult };
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      } finally {
        client.release();
      }
    },

    /** Test helper — issue token for Open session (M04 integration tests). */
    async issueTokenForSession(sessionId: string): Promise<{ qrPayload: string; expiresAt: string }> {
      const client = await pool.connect();
      try {
        await client.query("BEGIN");
        const issued = await issueQrToken(client, sessionId);
        await client.query("COMMIT");
        return { qrPayload: issued.qrPayload, expiresAt: issued.expiresAt };
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      } finally {
        client.release();
      }
    },

    clearIdempotencyCache(): void {
      idempotencyCache.clear();
    },
  };
}

export type CheckInRepository = ReturnType<typeof createCheckInRepository>;
