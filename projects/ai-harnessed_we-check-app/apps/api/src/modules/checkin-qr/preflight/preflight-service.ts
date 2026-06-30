import {
  ErrorCode,
  QrTokenStatus,
  SessionStatus,
  isQrTokenExpired,
  isWithinAttendanceWindow,
} from "@wecheck/domain";
import type { DbPool } from "../../../infra/db.js";
import { now } from "../../../infra/clock.js";
import { EnrollmentRepository } from "../../roster-enrollment/enrollment-repository.js";
import { QrTokenRepository, SecurityAuditRepository } from "../repositories.js";
import {
  preflightFailureMessage,
  SESSION_MISMATCH_CODE,
} from "./preflight-response.js";
import type {
  PreflightErrorCode,
  PreflightFailureResponse,
  PreflightResponse,
  PreflightSuccessResponse,
} from "./types.js";

/**
 * BR-15 — read-only token validation before GPS capture.
 * Evaluation order per validation-rules §3.6a.
 */
export class PreflightService {
  private readonly tokens: QrTokenRepository;
  private readonly securityAudit: SecurityAuditRepository;
  private readonly enrollments: EnrollmentRepository;

  constructor(private readonly db: DbPool) {
    this.tokens = new QrTokenRepository(db);
    this.securityAudit = new SecurityAuditRepository();
    this.enrollments = new EnrollmentRepository(db);
  }

  async validate(
    tokenId: string,
    studentId: string,
    expectedSessionId?: string | null,
  ): Promise<PreflightResponse> {
    const current = now();

    const token = await this.tokens.findById(tokenId);
    if (!token) {
      return this.fail(ErrorCode.TokenNotFound);
    }

    if (expectedSessionId && expectedSessionId !== token.sessionId) {
      return this.fail(SESSION_MISMATCH_CODE);
    }

    if (
      token.status === QrTokenStatus.Expired ||
      isQrTokenExpired(token.issuedAt, current)
    ) {
      return this.fail(ErrorCode.ExpiredQr);
    }

    if (token.status === QrTokenStatus.Consumed) {
      await this.logTokenReuse({
        sessionId: token.sessionId,
        qrTokenId: token.id,
        studentId,
        consumedByStudentId: token.consumedByStudentId,
      });
      return this.fail(ErrorCode.TokenAlreadyUsed);
    }

    const session = await this.tokens.findSessionDisplayContext(token.sessionId);
    if (!session || session.status !== SessionStatus.Active) {
      return this.fail(ErrorCode.SessionNotActive);
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
      return this.fail(ErrorCode.SessionNotActive);
    }

    const enrolled = await this.enrollments.exists(
      studentId,
      session.classId,
      session.subjectId,
    );
    if (!enrolled) {
      return this.fail(ErrorCode.NotEnrolled);
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

  private fail(errorCode: PreflightErrorCode): PreflightFailureResponse {
    return {
      outcome: errorCode,
      message: preflightFailureMessage(errorCode),
      errorCode,
    };
  }

  private async logTokenReuse(input: {
    sessionId: string;
    qrTokenId: string;
    studentId: string;
    consumedByStudentId: string | null;
  }): Promise<void> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      await this.securityAudit.insert(client, {
        eventType: "TokenReuseAlert",
        sessionId: input.sessionId,
        qrTokenId: input.qrTokenId,
        studentId: input.studentId,
        details: {
          consumedByStudentId: input.consumedByStudentId,
          source: "preflight",
        },
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
