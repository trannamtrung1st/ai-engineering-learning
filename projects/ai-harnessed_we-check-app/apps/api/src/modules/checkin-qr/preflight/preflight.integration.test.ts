import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import {
  AttendanceStatus,
  ErrorCode,
  QR_TOKEN_TTL_MS,
  QrTokenStatus,
  SESSION_COOKIE_NAME,
  SessionStatus,
  UserRole,
} from "@wecheck/domain";
import {
  createPool,
  setPool,
  closePool,
  type DbPool,
} from "../../../infra/db.js";
import { runMigrations } from "../../../infra/migrate.js";
import { buildApp } from "../../../server.js";
import {
  createTestUser,
  SessionStore,
  truncateAuthTables,
} from "../../../auth/session-store.js";
import { resetClock, setClock, now } from "../../../infra/clock.js";
import { truncateRosterTables } from "../../roster-enrollment/roster-service.js";
import { SessionService } from "../../session-management/session-service.js";
import { truncateCheckInTables } from "../check-in-service.js";
import { PreflightService } from "./preflight-service.js";
import { SESSION_MISMATCH_CODE } from "./preflight-response.js";
import { withIntegrationTestDbReset } from "../../../infra/integration-test-lock.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

const CLASS_HESD_01 = "10000000-0000-4000-8000-000000000101";
const SUBJECT_SWE_101 = "20000000-0000-4000-8000-000000000201";

const ROOM_LAT = 10.762622;
const ROOM_LNG = 106.660172;
const IN_RADIUS_LAT = 10.7627;
const IN_RADIUS_LNG = 106.6602;

/**
 * Traceability: AC-07 FR-07 BR-03 BR-11 BR-15
 */
describe("check-in preflight integration (AC-07, FR-07, BR-03, BR-11, BR-15)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let store: SessionStore;
  let sessionService: SessionService;
  let preflightService: PreflightService;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    store = new SessionStore(db);
    sessionService = new SessionService(db);
    preflightService = new PreflightService(db);
  });

  after(async () => {
    await sessionService.qr.stopAll();
    resetClock();
    await app.close();
    await closePool();
  });

  async function resetDb(afterTruncate?: () => Promise<void>): Promise<void> {
    await withIntegrationTestDbReset(db, async () => {
      await sessionService.qr.stopAll();
      await truncateCheckInTables(db);
      await truncateRosterTables(db);
      await truncateAuthTables(db);
      resetClock();
      if (afterTruncate) await afterTruncate();
    });
  }

  async function seedReferenceData(): Promise<void> {
    await db.query(
      `INSERT INTO classes (id, code, name) VALUES ($1, 'HESD-01', 'HESD Cohort A')
       ON CONFLICT (id) DO NOTHING`,
      [CLASS_HESD_01],
    );
    await db.query(
      `INSERT INTO subjects (id, code, name) VALUES ($1, 'SWE-101', 'Software Engineering 101')
       ON CONFLICT (id) DO NOTHING`,
      [SUBJECT_SWE_101],
    );
  }

  async function seedInstructor(): Promise<{ userId: string; cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId: "GV2026001",
      displayName: "Instructor One",
      email: "instructor@example.edu.vn",
      role: UserRole.Instructor,
    });
    await db.query(
      `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
       VALUES ($1, $2, $3)`,
      [userId, CLASS_HESD_01, SUBJECT_SWE_101],
    );
    const session = await store.createSession(userId);
    return { userId, cookie: `${SESSION_COOKIE_NAME}=${session.id}` };
  }

  async function seedStudent(
    suffix = "1",
  ): Promise<{ userId: string; cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId: `SV202600${suffix}`,
      displayName: `Student ${suffix}`,
      email: `student${suffix}@example.edu.vn`,
      role: UserRole.Student,
    });
    const session = await store.createSession(userId);
    return { userId, cookie: `${SESSION_COOKIE_NAME}=${session.id}` };
  }

  async function seedEnrollment(studentId: string): Promise<void> {
    await db.query(
      `INSERT INTO enrollments (student_id, class_id, subject_id)
       VALUES ($1, $2, $3)`,
      [studentId, CLASS_HESD_01, SUBJECT_SWE_101],
    );
  }

  function futureStart(): string {
    return new Date(now().getTime() + 60 * 60 * 1000).toISOString();
  }

  async function seedActiveSession(): Promise<{
    sessionId: string;
    instructor: { userId: string; cookie: string };
    student: { userId: string; cookie: string };
    tokenId: string;
  }> {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent();
    await seedEnrollment(student.userId);

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    await sessionService.open(created.id, instructor.userId, UserRole.Instructor);

    const qr = await sessionService.getCurrentQr(
      created.id,
      instructor.userId,
      UserRole.Instructor,
    );

    return {
      sessionId: created.id,
      instructor,
      student,
      tokenId: qr.tokenId,
    };
  }

  function checkInPayload(tokenId: string) {
    return {
      tokenId,
      latitude: IN_RADIUS_LAT,
      longitude: IN_RADIUS_LNG,
      spoofMetadata: { mockLocationDetected: false, accuracyMeters: 12.5, platform: "android" },
    };
  }

  async function assertNoPreflightWrites(
    sessionId: string,
    studentId: string,
    tokenId: string,
    expectedTokenStatus: string,
    expectedAttendanceStatus: string,
  ): Promise<void> {
    const token = await db.query<{ status: string }>(
      `SELECT status FROM qr_tokens WHERE id = $1`,
      [tokenId],
    );
    assert.equal(token.rows[0]?.status, expectedTokenStatus);

    const attendance = await db.query<{ status: string }>(
      `SELECT status FROM attendance_records WHERE session_id = $1 AND student_id = $2`,
      [sessionId, studentId],
    );
    assert.equal(attendance.rows[0]?.status, expectedAttendanceStatus);

    const attempts = await db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM check_in_attempts WHERE qr_token_id = $1`,
      [tokenId],
    );
    assert.equal(attempts.rows[0]?.count, "0");
  }

  it("PreflightService.validate returns Valid without DB writes (TC-BR-15-001, TC-FR-07-021)", async () => {
    const { sessionId, student, tokenId } = await seedActiveSession();

    const result = await preflightService.validate(tokenId, student.userId, sessionId);

    assert.equal(result.outcome, "Valid");
    if (result.outcome === "Valid") {
      assert.equal(result.tokenId, tokenId);
      assert.equal(result.sessionId, sessionId);
      assert.equal(result.session.classCode, "HESD-01");
      assert.equal(result.session.subjectCode, "SWE-101");
      assert.equal(result.session.roomName, "Phòng A201");
      assert.equal(result.session.status, SessionStatus.Active);
    }

    await assertNoPreflightWrites(
      sessionId,
      student.userId,
      tokenId,
      QrTokenStatus.Valid,
      AttendanceStatus.Pending,
    );
  });

  it("GET /check-in/tokens/:tokenId/preflight returns 200 with session summary (TC-AC-07-017, TC-BR-15-003)", async () => {
    const { sessionId, student, tokenId } = await seedActiveSession();

    const response = await app.inject({
      method: "GET",
      url: `/api/v1/check-in/tokens/${tokenId}/preflight?sessionId=${sessionId}`,
      headers: { cookie: student.cookie },
    });

    assert.equal(response.statusCode, 200);
    const body = response.json<{
      outcome: string;
      tokenId: string;
      sessionId: string;
      session: { classCode: string; subjectCode: string; roomName: string; status: string };
    }>();
    assert.equal(body.outcome, "Valid");
    assert.equal(body.tokenId, tokenId);
    assert.equal(body.sessionId, sessionId);
    assert.equal(body.session.classCode, "HESD-01");
    assert.equal(body.session.subjectCode, "SWE-101");
    assert.equal(body.session.roomName, "Phòng A201");
    assert.equal(body.session.status, SessionStatus.Active);

    await assertNoPreflightWrites(
      sessionId,
      student.userId,
      tokenId,
      QrTokenStatus.Valid,
      AttendanceStatus.Pending,
    );
  });

  it("preflight rejects ExpiredQr, NotEnrolled, SessionMismatch, TokenNotFound (TC-AC-07-018)", async () => {
    const { sessionId, instructor, student, tokenId } = await seedActiveSession();
    const studentB = await seedStudent("2");

    const qr = await app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}/qr/current`,
      headers: { cookie: instructor.cookie },
    });
    const issuedAt = new Date(qr.json<{ issuedAt: string }>().issuedAt);
    setClock(new Date(issuedAt.getTime() + QR_TOKEN_TTL_MS + 1000));

    const expired = await app.inject({
      method: "GET",
      url: `/api/v1/check-in/tokens/${tokenId}/preflight`,
      headers: { cookie: student.cookie },
    });
    assert.equal(expired.statusCode, 403);
    const expiredBody = expired.json<{ outcome: string; errorCode: string }>();
    assert.equal(expiredBody.outcome, ErrorCode.ExpiredQr);
    assert.equal(expiredBody.errorCode, ErrorCode.ExpiredQr);

    resetClock();
    const notEnrolled = await app.inject({
      method: "GET",
      url: `/api/v1/check-in/tokens/${tokenId}/preflight`,
      headers: { cookie: studentB.cookie },
    });
    assert.equal(notEnrolled.statusCode, 403);
    const notEnrolledBody = notEnrolled.json<{ outcome: string; errorCode: string }>();
    assert.equal(notEnrolledBody.outcome, ErrorCode.NotEnrolled);
    assert.equal(notEnrolledBody.errorCode, ErrorCode.NotEnrolled);

    const wrongSession = randomUUID();
    const mismatch = await app.inject({
      method: "GET",
      url: `/api/v1/check-in/tokens/${tokenId}/preflight?sessionId=${wrongSession}`,
      headers: { cookie: student.cookie },
    });
    assert.equal(mismatch.statusCode, 403);
    const mismatchBody = mismatch.json<{ outcome: string; errorCode: string }>();
    assert.equal(mismatchBody.outcome, SESSION_MISMATCH_CODE);
    assert.equal(mismatchBody.errorCode, SESSION_MISMATCH_CODE);

    const unknown = await app.inject({
      method: "GET",
      url: `/api/v1/check-in/tokens/${randomUUID()}/preflight`,
      headers: { cookie: student.cookie },
    });
    assert.equal(unknown.statusCode, 404);
    const unknownBody = unknown.json<{ outcome: string; errorCode: string }>();
    assert.equal(unknownBody.outcome, ErrorCode.TokenNotFound);
    assert.equal(unknownBody.errorCode, ErrorCode.TokenNotFound);
  });

  it("preflight rejects expired token at T + 31 s without writes (TC-BR-03-021, BR-03)", async () => {
    const { sessionId, student, tokenId, instructor } = await seedActiveSession();

    const qr = await app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}/qr/current`,
      headers: { cookie: instructor.cookie },
    });
    const issuedAt = new Date(qr.json<{ issuedAt: string }>().issuedAt);
    setClock(new Date(issuedAt.getTime() + QR_TOKEN_TTL_MS + 1000));

    const response = await app.inject({
      method: "GET",
      url: `/api/v1/check-in/tokens/${tokenId}/preflight`,
      headers: { cookie: student.cookie },
    });

    assert.equal(response.statusCode, 403);
    const body = response.json<{ outcome: string; errorCode: string; message: string }>();
    assert.equal(body.outcome, ErrorCode.ExpiredQr);
    assert.equal(body.errorCode, ErrorCode.ExpiredQr);
    assert.equal(body.message, "Mã QR đã hết hạn, vui lòng quét mã mới");

    await assertNoPreflightWrites(
      sessionId,
      student.userId,
      tokenId,
      QrTokenStatus.Valid,
      AttendanceStatus.Pending,
    );
  });

  it("preflight rejects Consumed token with security log, no attendance writes (TC-BR-11-017, TC-BR-15-009)", async () => {
    const { sessionId, student, tokenId } = await seedActiveSession();
    const studentB = await seedStudent("2");
    await seedEnrollment(studentB.userId);

    await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: student.cookie },
      payload: checkInPayload(tokenId),
    });

    const auditBefore = await db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM security_audit_logs WHERE qr_token_id = $1`,
      [tokenId],
    );

    const response = await app.inject({
      method: "GET",
      url: `/api/v1/check-in/tokens/${tokenId}/preflight`,
      headers: { cookie: studentB.cookie },
    });

    assert.equal(response.statusCode, 403);
    const body = response.json<{ outcome: string; errorCode: string; message: string }>();
    assert.equal(body.outcome, ErrorCode.TokenAlreadyUsed);
    assert.equal(body.errorCode, ErrorCode.TokenAlreadyUsed);
    assert.equal(body.message, "Mã QR đã được sử dụng");

    const auditAfter = await db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM security_audit_logs
       WHERE qr_token_id = $1 AND event_type = 'TokenReuseAlert' AND student_id = $2`,
      [tokenId, studentB.userId],
    );
    assert.ok(Number.parseInt(auditAfter.rows[0]?.count ?? "0", 10) > 0);
    assert.ok(
      Number.parseInt(auditAfter.rows[0]?.count ?? "0", 10) >
        Number.parseInt(auditBefore.rows[0]?.count ?? "0", 10),
    );

    const attendanceB = await db.query<{ status: string }>(
      `SELECT status FROM attendance_records WHERE session_id = $1 AND student_id = $2`,
      [sessionId, studentB.userId],
    );
    assert.notEqual(attendanceB.rows[0]?.status, AttendanceStatus.Present);

    const token = await db.query<{ status: string }>(
      `SELECT status FROM qr_tokens WHERE id = $1`,
      [tokenId],
    );
    assert.equal(token.rows[0]?.status, QrTokenStatus.Consumed);
  });

  it("preflight short-circuits at TokenNotFound before session lookup (TC-BR-15-002)", async () => {
    const { student } = await seedActiveSession();
    const unknownId = randomUUID();

    const result = await preflightService.validate(unknownId, student.userId);

    assert.equal(result.outcome, ErrorCode.TokenNotFound);
    assert.equal(result.errorCode, ErrorCode.TokenNotFound);
  });

  it("preflight for Closed session returns SessionNotActive (TC-BR-15-008)", async () => {
    const { sessionId, student, tokenId, instructor } = await seedActiveSession();

    await sessionService.close(sessionId, instructor.userId, UserRole.Instructor);

    const current = now();
    await db.query(
      `UPDATE qr_tokens
       SET status = $2, issued_at = $3, expires_at = $4
       WHERE id = $1`,
      [
        tokenId,
        QrTokenStatus.Valid,
        current,
        new Date(current.getTime() + QR_TOKEN_TTL_MS),
      ],
    );

    const response = await app.inject({
      method: "GET",
      url: `/api/v1/check-in/tokens/${tokenId}/preflight`,
      headers: { cookie: student.cookie },
    });

    assert.equal(response.statusCode, 403);
    const body = response.json<{ outcome: string; errorCode: string }>();
    assert.equal(body.outcome, ErrorCode.SessionNotActive);
    assert.equal(body.errorCode, ErrorCode.SessionNotActive);

    await assertNoPreflightWrites(
      sessionId,
      student.userId,
      tokenId,
      QrTokenStatus.Valid,
      AttendanceStatus.Absent,
    );
  });

  it("unauthenticated GET preflight returns 401 (TC-BR-15-010, FR-07)", async () => {
    const { tokenId } = await seedActiveSession();

    const response = await app.inject({
      method: "GET",
      url: `/api/v1/check-in/tokens/${tokenId}/preflight`,
    });

    assert.equal(response.statusCode, 401);
  });

  it("instructor denied GET preflight lacking checkin:submit (TC-FR-07-016)", async () => {
    const { tokenId, instructor } = await seedActiveSession();

    const response = await app.inject({
      method: "GET",
      url: `/api/v1/check-in/tokens/${tokenId}/preflight`,
      headers: { cookie: instructor.cookie },
    });

    assert.equal(response.statusCode, 403);
  });
});
