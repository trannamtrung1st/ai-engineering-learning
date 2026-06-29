import {
  AttendanceStatus,
  ErrorCode,
  QrTokenStatus,
  SessionStatus,
  blocksDuplicateCheckIn,
  isQrTokenExpired,
  isWithinAttendanceWindow,
} from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { now } from "../../infra/clock.js";
import { EnrollmentRepository } from "../roster-enrollment/enrollment-repository.js";
import {
  checkInFailureMessage,
  checkInSuccessMessage,
  preflightFailureMessage,
  SESSION_MISMATCH_CODE,
} from "./check-in-response.js";
import { verifyLocation } from "./geo-verification.js";
import {
  CheckInAttemptRepository,
  QrTokenRepository,
  SecurityAuditRepository,
} from "./repositories.js";
import type {
  AttendanceCheckInRow,
  CheckInFailureResponse,
  CheckInRequestBody,
  CheckInSuccessResponse,
  PreflightErrorCode,
  PreflightFailureResponse,
  PreflightResponse,
  PreflightSuccessResponse,
} from "./types.js";
import { hasGpsCoordinates } from "./validation.js";

export type CheckInServiceResult = CheckInSuccessResponse | CheckInFailureResponse;

interface FailureContext {
  sessionId?: string;
  qrTokenId?: string | null;
  distanceMeters?: number | null;
  spoofFlags?: Record<string, unknown> | null;
  priorCheckedInAt?: string;
}

export class CheckInService {
  private readonly tokens: QrTokenRepository;
  private readonly attempts: CheckInAttemptRepository;
  private readonly securityAudit: SecurityAuditRepository;
  private readonly enrollments: EnrollmentRepository;

  constructor(private readonly db: DbPool) {
    this.tokens = new QrTokenRepository(db);
    this.attempts = new CheckInAttemptRepository();
    this.securityAudit = new SecurityAuditRepository();
    this.enrollments = new EnrollmentRepository(db);
  }

  async sessionIdForToken(tokenId: string): Promise<string | null> {
    const token = await this.tokens.findById(tokenId);
    return token?.sessionId ?? null;
  }

  /** BR-15 — read-only token validation before GPS capture (no writes) */
  async preflight(
    tokenId: string,
    studentId: string,
    expectedSessionId?: string | null,
  ): Promise<PreflightResponse> {
    const current = now();

    const token = await this.tokens.findById(tokenId);
    if (!token) {
      return this.preflightFail(ErrorCode.TokenNotFound);
    }

    if (expectedSessionId && expectedSessionId !== token.sessionId) {
      return this.preflightFail(SESSION_MISMATCH_CODE);
    }

    const session = await this.tokens.findSessionDisplayContext(token.sessionId);
    if (!session || session.status !== SessionStatus.Active) {
      return this.preflightFail(ErrorCode.SessionNotActive);
    }

    if (
      !isWithinAttendanceWindow({
        status: session.status as SessionStatus,
        openedAt: session.openedAt,
        scheduledStart: session.scheduledStart,
        closedAt: session.closedAt,
        now: current,
      })
    ) {
      return this.preflightFail(ErrorCode.SessionNotActive);
    }

    if (
      token.status === QrTokenStatus.Expired ||
      isQrTokenExpired(token.issuedAt, current)
    ) {
      return this.preflightFail(ErrorCode.ExpiredQr);
    }

    if (token.status === QrTokenStatus.Consumed) {
      return this.preflightFail(ErrorCode.TokenAlreadyUsed);
    }

    const enrolled = await this.enrollments.exists(
      studentId,
      session.classId,
      session.subjectId,
    );
    if (!enrolled) {
      return this.preflightFail(ErrorCode.NotEnrolled);
    }

    return {
      outcome: "Valid",
      tokenId: token.id,
      sessionId: session.id,
      session: {
        classCode: session.classCode,
        subjectCode: session.subjectCode,
        roomName: session.roomName,
        status: session.status,
      },
    } satisfies PreflightSuccessResponse;
  }

  private preflightFail(errorCode: PreflightErrorCode): PreflightFailureResponse {
    return {
      outcome: errorCode,
      message: preflightFailureMessage(errorCode),
      errorCode,
    };
  }

  async submit(
    input: CheckInRequestBody,
    studentId: string,
    clientUserAgent?: string | null,
  ): Promise<CheckInServiceResult> {
    const current = now();

    const token = await this.tokens.findById(input.tokenId);
    if (!token) {
      return this.fail(ErrorCode.TokenNotFound, {}, studentId, current, clientUserAgent);
    }

    const session = await this.tokens.findSessionContext(token.sessionId);
    if (!session || session.status !== SessionStatus.Active) {
      return this.fail(
        ErrorCode.SessionNotActive,
        { sessionId: token.sessionId, qrTokenId: token.id },
        studentId,
        current,
        clientUserAgent,
      );
    }

    if (
      !isWithinAttendanceWindow({
        status: session.status as SessionStatus,
        openedAt: session.openedAt,
        scheduledStart: session.scheduledStart,
        closedAt: session.closedAt,
        now: current,
      })
    ) {
      return this.fail(
        ErrorCode.SessionNotActive,
        { sessionId: session.id, qrTokenId: token.id },
        studentId,
        current,
        clientUserAgent,
      );
    }

    if (
      token.status === QrTokenStatus.Expired ||
      isQrTokenExpired(token.issuedAt, current)
    ) {
      return this.fail(
        ErrorCode.ExpiredQr,
        { sessionId: session.id, qrTokenId: token.id },
        studentId,
        current,
        clientUserAgent,
      );
    }

    if (token.status === QrTokenStatus.Consumed) {
      await this.logSecurityEvent("TokenReuseAlert", {
        sessionId: session.id,
        qrTokenId: token.id,
        studentId,
        details: {
          consumedByStudentId: token.consumedByStudentId,
        },
      });
      return this.fail(
        ErrorCode.TokenAlreadyUsed,
        { sessionId: session.id, qrTokenId: token.id },
        studentId,
        current,
        clientUserAgent,
      );
    }

    const enrolled = await this.enrollments.exists(
      studentId,
      session.classId,
      session.subjectId,
    );
    if (!enrolled) {
      return this.fail(
        ErrorCode.NotEnrolled,
        { sessionId: session.id, qrTokenId: token.id },
        studentId,
        current,
        clientUserAgent,
      );
    }

    const attendance = await this.findAttendance(session.id, studentId);
    if (
      attendance &&
      blocksDuplicateCheckIn(
        attendance.status as AttendanceStatus,
        attendance.checkedInAt,
      )
    ) {
      return this.fail(
        ErrorCode.DuplicateCheckIn,
        {
          sessionId: session.id,
          qrTokenId: token.id,
          priorCheckedInAt: attendance.checkedInAt?.toISOString(),
        },
        studentId,
        current,
        clientUserAgent,
      );
    }

    if (!hasGpsCoordinates(input)) {
      return this.fail(
        ErrorCode.GpsDisabled,
        { sessionId: session.id, qrTokenId: token.id },
        studentId,
        current,
        clientUserAgent,
      );
    }

    const geo = verifyLocation(
      session.roomLatitude,
      session.roomLongitude,
      input.latitude!,
      input.longitude!,
      session.gpsRadiusMeters,
      input.spoofMetadata,
    );

    if (geo.spoofSuspected) {
      await this.logSecurityEvent("SpoofFlagged", {
        sessionId: session.id,
        qrTokenId: token.id,
        studentId,
        details: geo.spoofFlags ?? {},
      });
      return this.fail(
        ErrorCode.SpoofSuspected,
        {
          sessionId: session.id,
          qrTokenId: token.id,
          distanceMeters: geo.distanceMeters,
          spoofFlags: geo.spoofFlags,
        },
        studentId,
        current,
        clientUserAgent,
      );
    }

    if (!geo.withinRadius) {
      return this.fail(
        ErrorCode.OutOfRadius,
        {
          sessionId: session.id,
          qrTokenId: token.id,
          distanceMeters: geo.distanceMeters,
          spoofFlags: geo.spoofFlags,
        },
        studentId,
        current,
        clientUserAgent,
      );
    }

    return this.commitSuccess({
      tokenId: token.id,
      sessionId: session.id,
      studentId,
      checkedInAt: current,
      distanceMeters: geo.distanceMeters,
      spoofFlags: geo.spoofFlags,
      clientUserAgent,
    });
  }

  private async commitSuccess(input: {
    tokenId: string;
    sessionId: string;
    studentId: string;
    checkedInAt: Date;
    distanceMeters: number;
    spoofFlags: Record<string, unknown> | null;
    clientUserAgent?: string | null;
  }): Promise<CheckInSuccessResponse | CheckInFailureResponse> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");

      const token = await this.tokens.findByIdForUpdate(client, input.tokenId);
      if (!token) {
        await client.query("ROLLBACK");
        return this.fail(ErrorCode.TokenNotFound, {}, input.studentId, input.checkedInAt);
      }

      if (token.status === QrTokenStatus.Consumed) {
        await client.query("ROLLBACK");
        await this.logSecurityEvent("TokenReuseAlert", {
          sessionId: input.sessionId,
          qrTokenId: input.tokenId,
          studentId: input.studentId,
          details: { consumedByStudentId: token.consumedByStudentId },
        });
        return this.fail(
          ErrorCode.TokenAlreadyUsed,
          { sessionId: input.sessionId, qrTokenId: input.tokenId },
          input.studentId,
          input.checkedInAt,
          input.clientUserAgent,
        );
      }

      if (
        token.status === QrTokenStatus.Expired ||
        isQrTokenExpired(token.issuedAt, input.checkedInAt)
      ) {
        await client.query("ROLLBACK");
        return this.fail(
          ErrorCode.ExpiredQr,
          { sessionId: input.sessionId, qrTokenId: input.tokenId },
          input.studentId,
          input.checkedInAt,
          input.clientUserAgent,
        );
      }

      const attendanceResult = await client.query<{
        id: string;
        status: string;
        checked_in_at: Date | null;
        version: number;
      }>(
        `SELECT id, status, checked_in_at, version
         FROM attendance_records
         WHERE session_id = $1 AND student_id = $2
         FOR UPDATE`,
        [input.sessionId, input.studentId],
      );
      const attendance = attendanceResult.rows[0];
      if (
        attendance &&
        blocksDuplicateCheckIn(
          attendance.status as AttendanceStatus,
          attendance.checked_in_at,
        )
      ) {
        await this.attempts.insert(client, {
          sessionId: input.sessionId,
          studentId: input.studentId,
          qrTokenId: input.tokenId,
          outcome: ErrorCode.DuplicateCheckIn,
          attemptedAt: input.checkedInAt,
          distanceMeters: input.distanceMeters,
          spoofFlags: input.spoofFlags,
          clientUserAgent: input.clientUserAgent,
        });
        await client.query("COMMIT");
        return {
          outcome: ErrorCode.DuplicateCheckIn,
          message: checkInFailureMessage(ErrorCode.DuplicateCheckIn),
          errorCode: ErrorCode.DuplicateCheckIn,
          priorCheckedInAt: attendance.checked_in_at?.toISOString(),
        };
      }

      await this.attempts.insert(client, {
        sessionId: input.sessionId,
        studentId: input.studentId,
        qrTokenId: input.tokenId,
        outcome: "Success",
        attemptedAt: input.checkedInAt,
        distanceMeters: input.distanceMeters,
        spoofFlags: input.spoofFlags,
        clientUserAgent: input.clientUserAgent,
      });

      await this.tokens.consumeToken(
        client,
        input.tokenId,
        input.studentId,
        input.checkedInAt,
      );

      await client.query(
        `UPDATE attendance_records
         SET status = $3, checked_in_at = $4, updated_at = NOW(), version = version + 1
         WHERE session_id = $1 AND student_id = $2`,
        [
          input.sessionId,
          input.studentId,
          AttendanceStatus.Present,
          input.checkedInAt,
        ],
      );

      await client.query("COMMIT");

      return {
        outcome: "Success",
        message: checkInSuccessMessage(),
        attendance: {
          status: "Present",
          checkedInAt: input.checkedInAt.toISOString(),
        },
      };
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }

  private async findAttendance(
    sessionId: string,
    studentId: string,
  ): Promise<AttendanceCheckInRow | null> {
    const result = await this.db.query<{
      id: string;
      status: string;
      checked_in_at: Date | null;
      version: number;
    }>(
      `SELECT id, status, checked_in_at, version
       FROM attendance_records
       WHERE session_id = $1 AND student_id = $2`,
      [sessionId, studentId],
    );
    const row = result.rows[0];
    if (!row) {
      return null;
    }
    return {
      id: row.id,
      status: row.status,
      checkedInAt: row.checked_in_at,
      version: row.version,
    };
  }

  private async fail(
    errorCode: ErrorCode,
    ctx: FailureContext,
    studentId: string,
    attemptedAt: Date,
    clientUserAgent?: string | null,
  ): Promise<CheckInFailureResponse> {
    if (ctx.sessionId) {
      const client = await this.db.connect();
      try {
        await client.query("BEGIN");
        await this.attempts.insert(client, {
          sessionId: ctx.sessionId,
          studentId,
          qrTokenId: ctx.qrTokenId ?? null,
          outcome: errorCode,
          attemptedAt,
          distanceMeters: ctx.distanceMeters ?? null,
          spoofFlags: ctx.spoofFlags ?? null,
          clientUserAgent,
        });
        await client.query("COMMIT");
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      } finally {
        client.release();
      }
    }

    return {
      outcome: errorCode,
      message: checkInFailureMessage(errorCode),
      errorCode,
      ...(ctx.priorCheckedInAt ? { priorCheckedInAt: ctx.priorCheckedInAt } : {}),
    };
  }

  private async logSecurityEvent(
    eventType: string,
    input: {
      sessionId: string;
      qrTokenId: string;
      studentId: string;
      details: Record<string, unknown>;
    },
  ): Promise<void> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      await this.securityAudit.insert(client, {
        eventType,
        sessionId: input.sessionId,
        qrTokenId: input.qrTokenId,
        studentId: input.studentId,
        details: input.details,
      });
      await client.query("COMMIT");
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }
}

export async function truncateCheckInTables(db: DbPool): Promise<void> {
  await db.query(
    "TRUNCATE security_audit_logs, check_in_attempts, attendance_audit_logs, qr_tokens, attendance_records, sessions RESTART IDENTITY CASCADE",
  );
}
