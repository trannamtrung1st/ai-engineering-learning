import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import {
  AttendanceStatus,
  ErrorCode,
  QR_TOKEN_TTL_MS,
  QrTokenStatus,
  SESSION_COOKIE_NAME,
  UserRole,
} from "@wecheck/domain";
import {
  createPool,
  setPool,
  closePool,
  type DbPool,
} from "../../infra/db.js";
import { runMigrations } from "../../infra/migrate.js";
import { buildApp } from "../../server.js";
import {
  createTestUser,
  SessionStore,
  truncateAuthTables,
} from "../../auth/session-store.js";
import { resetClock, setClock, now } from "../../infra/clock.js";
import { truncateRosterTables } from "../roster-enrollment/roster-service.js";
import { SessionService } from "../session-management/session-service.js";
import { CheckInService, truncateCheckInTables } from "./check-in-service.js";
import { withIntegrationTestDbReset } from "../../infra/integration-test-lock.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

const CLASS_HESD_01 = "10000000-0000-4000-8000-000000000101";
const SUBJECT_SWE_101 = "20000000-0000-4000-8000-000000000201";

const ROOM_LAT = 10.762622;
const ROOM_LNG = 106.660172;
const IN_RADIUS_LAT = 10.7627;
const IN_RADIUS_LNG = 106.6602;
const OUT_RADIUS_LAT = 10.77;
const OUT_RADIUS_LNG = 106.67;

/**
 * Traceability: AC-06 AC-07 AC-08 AC-09 AC-10 FR-06 FR-07 FR-08 FR-09 FR-10
 * BR-02 BR-03 BR-04 BR-11 BR-12 NFR-02 NFR-06 NFR-12 NFR-21
 */
describe("checkin-qr integration (AC-06–AC-10, FR-06–FR-10, BR-02–BR-04, BR-11, BR-12, NFR-06, NFR-12)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let store: SessionStore;
  let sessionService: SessionService;
  let checkInService: CheckInService;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    store = new SessionStore(db);
    sessionService = new SessionService(db);
    checkInService = new CheckInService(db);
  });

  after(async () => {
    sessionService.qr.stopAll();
    resetClock();
    await app.close();
    await closePool();
  });

  async function resetDb(afterTruncate?: () => Promise<void>): Promise<void> {
    await withIntegrationTestDbReset(db, async () => {
      sessionService.qr.stopAll();
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

  function checkInPayload(tokenId: string, overrides: Record<string, unknown> = {}) {
    return {
      tokenId,
      latitude: IN_RADIUS_LAT,
      longitude: IN_RADIUS_LNG,
      spoofMetadata: { mockLocationDetected: false, accuracyMeters: 12.5, platform: "android" },
      ...overrides,
    };
  }

  it("GET /sessions/:id/qr/current returns rotating token with countdown (TC-AC-06-001, FR-06, NFR-06)", async () => {
    const { sessionId, instructor, tokenId: firstTokenId } = await seedActiveSession();

    const qr1 = await app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}/qr/current`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(qr1.statusCode, 200);
    const body1 = qr1.json<{
      tokenId: string;
      secondsRemaining: number;
      issuedAt: string;
      expiresAt: string;
      qrPayload: string;
    }>();
    assert.equal(body1.tokenId, firstTokenId);
    assert.ok(body1.secondsRemaining >= 29 && body1.secondsRemaining <= 30);
    assert.ok(body1.qrPayload.includes("wecheck://check-in"));

    const issuedAt = new Date(body1.issuedAt);
    const expiresAt = new Date(body1.expiresAt);
    assert.equal(expiresAt.getTime() - issuedAt.getTime(), QR_TOKEN_TTL_MS);

    setClock(new Date(issuedAt.getTime() + QR_TOKEN_TTL_MS));
    await sessionService.qr.rotate(sessionId);

    const qr2 = await app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}/qr/current`,
      headers: { cookie: instructor.cookie },
    });
    const body2 = qr2.json<{ tokenId: string }>();
    assert.notEqual(body2.tokenId, firstTokenId);
  });

  it("POST /check-in success marks Present and consumes token (TC-AC-07-001, FR-07, FR-08, BR-02)", async () => {
    const { sessionId, student, tokenId } = await seedActiveSession();

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: student.cookie },
      payload: checkInPayload(tokenId),
    });

    assert.equal(response.statusCode, 200);
    const body = response.json<{
      outcome: string;
      message: string;
      attendance: { status: string; checkedInAt: string };
    }>();
    assert.equal(body.outcome, "Success");
    assert.equal(body.message, "Điểm danh thành công");
    assert.equal(body.attendance.status, "Present");

    const attendance = await db.query<{ status: string }>(
      `SELECT status FROM attendance_records WHERE session_id = $1 AND student_id = $2`,
      [sessionId, student.userId],
    );
    assert.equal(attendance.rows[0]?.status, AttendanceStatus.Present);

    const token = await db.query<{ status: string }>(
      `SELECT status FROM qr_tokens WHERE id = $1`,
      [tokenId],
    );
    assert.equal(token.rows[0]?.status, QrTokenStatus.Consumed);

    const attempt = await db.query<{
      outcome: string;
      distance_meters: string;
    }>(
      `SELECT outcome, distance_meters FROM check_in_attempts
       WHERE session_id = $1 AND student_id = $2 ORDER BY attempted_at DESC LIMIT 1`,
      [sessionId, student.userId],
    );
    assert.equal(attempt.rows[0]?.outcome, "Success");
    assert.ok(Number.parseFloat(attempt.rows[0]?.distance_meters ?? "999") <= 100);
  });

  it("does not persist raw client coordinates (TC-AC-08-004, NFR-12, FR-08)", async () => {
    const { student, tokenId } = await seedActiveSession();

    await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: student.cookie },
      payload: checkInPayload(tokenId),
    });

    const columns = await db.query<{ column_name: string }>(
      `SELECT column_name FROM information_schema.columns
       WHERE table_name = 'check_in_attempts' AND column_name ILIKE '%lat%'`,
    );
    assert.equal(columns.rowCount, 0);

    const columns2 = await db.query<{ column_name: string }>(
      `SELECT column_name FROM information_schema.columns
       WHERE table_name = 'attendance_records' AND column_name ILIKE '%lat%'`,
    );
    assert.equal(columns2.rowCount, 0);
  });

  it("POST /check-in OutOfRadius when outside gps radius (TC-AC-08-002, BR-02, FR-08)", async () => {
    const { sessionId, student, tokenId } = await seedActiveSession();

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: student.cookie },
      payload: checkInPayload(tokenId, {
        latitude: OUT_RADIUS_LAT,
        longitude: OUT_RADIUS_LNG,
      }),
    });

    assert.equal(response.statusCode, 400);
    const body = response.json<{ outcome: string; errorCode: string }>();
    assert.equal(body.outcome, ErrorCode.OutOfRadius);
    assert.equal(body.errorCode, ErrorCode.OutOfRadius);

    const attendance = await db.query<{ status: string }>(
      `SELECT status FROM attendance_records WHERE session_id = $1 AND student_id = $2`,
      [sessionId, student.userId],
    );
    assert.equal(attendance.rows[0]?.status, AttendanceStatus.Pending);

    const attempt = await db.query<{ outcome: string; distance_meters: string }>(
      `SELECT outcome, distance_meters FROM check_in_attempts
       WHERE session_id = $1 AND student_id = $2 ORDER BY attempted_at DESC LIMIT 1`,
      [sessionId, student.userId],
    );
    assert.equal(attempt.rows[0]?.outcome, ErrorCode.OutOfRadius);
    assert.ok(Number.parseFloat(attempt.rows[0]?.distance_meters ?? "0") > 100);
  });

  it("POST /check-in ExpiredQr after 31 seconds (TC-AC-06-002, BR-03)", async () => {
    const { sessionId, student, tokenId, instructor } = await seedActiveSession();

    const qr = await app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}/qr/current`,
      headers: { cookie: instructor.cookie },
    });
    const issuedAt = new Date(qr.json<{ issuedAt: string }>().issuedAt);
    setClock(new Date(issuedAt.getTime() + QR_TOKEN_TTL_MS + 1000));

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: student.cookie },
      payload: checkInPayload(tokenId),
    });

    assert.equal(response.statusCode, 400);
    const body = response.json<{ outcome: string; errorCode: string; message: string }>();
    assert.equal(body.outcome, ErrorCode.ExpiredQr);
    assert.equal(body.message, "Mã QR đã hết hạn, vui lòng quét mã mới");
  });

  it("POST /check-in DuplicateCheckIn when already Present (TC-AC-09-001, BR-04, FR-09)", async () => {
    const { sessionId, student, tokenId, instructor } = await seedActiveSession();

    await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: student.cookie },
      payload: checkInPayload(tokenId),
    });

    const qr2 = await sessionService.getCurrentQr(
      sessionId,
      instructor.userId,
      UserRole.Instructor,
    );

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: student.cookie },
      payload: checkInPayload(qr2.tokenId),
    });

    assert.equal(response.statusCode, 409);
    const body = response.json<{
      outcome: string;
      errorCode: string;
      message: string;
      priorCheckedInAt?: string;
    }>();
    assert.equal(body.outcome, ErrorCode.DuplicateCheckIn);
    assert.equal(body.message, "Bạn đã điểm danh buổi học này rồi");
    assert.ok(body.priorCheckedInAt);

    const attempts = await db.query<{ outcome: string }>(
      `SELECT outcome FROM check_in_attempts
       WHERE session_id = $1 AND student_id = $2 ORDER BY attempted_at`,
      [sessionId, student.userId],
    );
    assert.equal(attempts.rows.length, 2);
    assert.equal(attempts.rows[1]?.outcome, ErrorCode.DuplicateCheckIn);
  });

  it("POST /check-in TokenAlreadyUsed for consumed token by second student (TC-AC-09-002, BR-11)", async () => {
    const { sessionId, student, tokenId } = await seedActiveSession();
    const studentB = await seedStudent("2");
    await seedEnrollment(studentB.userId);

    await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: student.cookie },
      payload: checkInPayload(tokenId),
    });

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: studentB.cookie },
      payload: checkInPayload(tokenId),
    });

    assert.equal(response.statusCode, 400);
    const body = response.json<{ outcome: string; errorCode: string; message: string }>();
    assert.equal(body.outcome, ErrorCode.TokenAlreadyUsed);
    assert.equal(body.message, "Mã QR đã được sử dụng");

    const audit = await db.query<{ event_type: string; session_id: string; qr_token_id: string; student_id: string }>(
      `SELECT event_type, session_id, qr_token_id, student_id
       FROM security_audit_logs WHERE event_type = 'TokenReuseAlert'`,
    );
    assert.ok(audit.rowCount! >= 1);
    assert.equal(audit.rows[0]?.session_id, sessionId);
    assert.equal(audit.rows[0]?.qr_token_id, tokenId);
    assert.equal(audit.rows[0]?.student_id, studentB.userId);
  });

  it("POST /check-in GpsDisabled without coordinates (TC-BR-12-001, BR-12, NFR-19)", async () => {
    const { sessionId, student, tokenId } = await seedActiveSession();

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: student.cookie },
      payload: { tokenId },
    });

    assert.equal(response.statusCode, 422);

    const response2 = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: student.cookie },
      payload: { tokenId, latitude: IN_RADIUS_LAT, longitude: IN_RADIUS_LNG, gpsAvailable: false },
    });

    assert.equal(response2.statusCode, 400);
    const body = response2.json<{ outcome: string; errorCode: string }>();
    assert.equal(body.outcome, ErrorCode.GpsDisabled);

    const attendance = await db.query<{ status: string }>(
      `SELECT status FROM attendance_records WHERE session_id = $1 AND student_id = $2`,
      [sessionId, student.userId],
    );
    assert.equal(attendance.rows[0]?.status, AttendanceStatus.Pending);
  });

  it("POST /check-in SpoofSuspected for mock location (TC-FR-10-001, AC-10, FR-10)", async () => {
    const { sessionId, student, tokenId } = await seedActiveSession();

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: student.cookie },
      payload: checkInPayload(tokenId, {
        spoofMetadata: { mockLocationDetected: true, platform: "android" },
      }),
    });

    assert.equal(response.statusCode, 400);
    const body = response.json<{ outcome: string; errorCode: string; message: string }>();
    assert.equal(body.outcome, ErrorCode.SpoofSuspected);
    assert.equal(body.message, "Không thể xác minh vị trí. Liên hệ giảng viên.");

    const attempt = await db.query<{ outcome: string; spoof_flags: { mockLocationDetected: boolean } }>(
      `SELECT outcome, spoof_flags FROM check_in_attempts
       WHERE session_id = $1 AND student_id = $2 ORDER BY attempted_at DESC LIMIT 1`,
      [sessionId, student.userId],
    );
    assert.equal(attempt.rows[0]?.outcome, ErrorCode.SpoofSuspected);
    assert.equal(attempt.rows[0]?.spoof_flags?.mockLocationDetected, true);

    const audit = await db.query<{ event_type: string }>(
      `SELECT event_type FROM security_audit_logs WHERE event_type = 'SpoofFlagged'`,
    );
    assert.ok(audit.rowCount! >= 1);
  });

  it("CheckInService.submit enforces duplicate guard (TC-AC-09-004, BR-04, NFR-02)", async () => {
    const { sessionId, student, tokenId, instructor } = await seedActiveSession();

    const first = await checkInService.submit(
      {
        tokenId,
        latitude: IN_RADIUS_LAT,
        longitude: IN_RADIUS_LNG,
        spoofMetadata: { accuracyMeters: 12, platform: "android" },
      },
      student.userId,
    );
    assert.equal(first.outcome, "Success");

    const qr2 = await sessionService.getCurrentQr(
      sessionId,
      instructor.userId,
      UserRole.Instructor,
    );

    const second = await checkInService.submit(
      {
        tokenId: qr2.tokenId,
        latitude: IN_RADIUS_LAT,
        longitude: IN_RADIUS_LNG,
        spoofMetadata: { accuracyMeters: 12, platform: "android" },
      },
      student.userId,
    );
    assert.equal(second.outcome, ErrorCode.DuplicateCheckIn);

    const count = await db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM attendance_records
       WHERE session_id = $1 AND student_id = $2 AND status = 'Present'`,
      [sessionId, student.userId],
    );
    assert.equal(count.rows[0]?.count, "1");
  });

  it("POST /check-in TokenNotFound for unknown token (TC-FR-07-010)", async () => {
    await seedActiveSession();
    const student = await seedStudent("99");
    const session = await store.createSession(student.userId);

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${session.id}` },
      payload: checkInPayload("00000000-0000-4000-8000-000000009999"),
    });

    assert.equal(response.statusCode, 404);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.TokenNotFound,
    );
  });

  it("POST /check-in NotEnrolled for unlisted student (TC-FR-03-010, FR-07)", async () => {
    const { tokenId } = await seedActiveSession();
    const outsider = await seedStudent("99");

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: outsider.cookie },
      payload: checkInPayload(tokenId),
    });

    assert.equal(response.statusCode, 403);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.NotEnrolled,
    );
  });

  it("GET /sessions/:id/qr/current rejected when session not Active (TC-AC-06-003)", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Draft session",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    const response = await app.inject({
      method: "GET",
      url: `/api/v1/sessions/${created.id}/qr/current`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(response.statusCode, 409);
  });

  it("structured logs exclude raw GPS after check-in (TC-NFR-12-007, NFR-12, NFR-21)", async () => {
    const logLines: string[] = [];
    const loggingApp = await buildApp({
      db,
      logger: {
        level: "info",
        stream: {
          write(line: string) {
            logLines.push(line);
          },
        },
      },
    });

    try {
      const { sessionId, student, tokenId } = await seedActiveSession();
      const lat = 10.7627;
      const lng = 106.6602;

      const success = await loggingApp.inject({
        method: "POST",
        url: "/api/v1/check-in",
        headers: { cookie: student.cookie },
        payload: checkInPayload(tokenId, { latitude: lat, longitude: lng }),
      });

      assert.equal(success.statusCode, 200);
      const requestId = success.headers["x-request-id"];
      assert.ok(typeof requestId === "string");

      const successLogs = logLines.filter((line) => line.includes(requestId));
      assert.ok(successLogs.length > 0);
      const successBlob = successLogs.join("\n");
      assert.ok(successBlob.includes("/api/v1/check-in"));
      assert.ok(successBlob.includes(sessionId));
      assert.ok(successBlob.includes('"outcome":"Success"') || successBlob.includes('"outcome": "Success"'));
      assert.ok(!successBlob.includes(String(lat)));
      assert.ok(!successBlob.includes(String(lng)));
      assert.ok(!/latitude/i.test(successBlob));
      assert.ok(!/longitude/i.test(successBlob));

      await resetDb(seedReferenceData);
      const instructor = await seedInstructor();
      const outStudent = await seedStudent("out");
      await seedEnrollment(outStudent.userId);
      const created = await sessionService.create(
        {
          classId: CLASS_HESD_01,
          subjectId: SUBJECT_SWE_101,
          title: "OutOfRadius session",
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

      const fail = await loggingApp.inject({
        method: "POST",
        url: "/api/v1/check-in",
        headers: { cookie: outStudent.cookie },
        payload: checkInPayload(qr.tokenId, {
          latitude: OUT_RADIUS_LAT,
          longitude: OUT_RADIUS_LNG,
        }),
      });

      assert.equal(fail.statusCode, 400);
      const failRequestId = fail.headers["x-request-id"];
      assert.ok(typeof failRequestId === "string");

      const failLogs = logLines.filter((line) => line.includes(failRequestId));
      assert.ok(failLogs.length > 0);
      const failBlob = failLogs.join("\n");
      assert.ok(failBlob.includes("OutOfRadius"));
      assert.ok(!failBlob.includes(String(OUT_RADIUS_LAT)));
      assert.ok(!failBlob.includes(String(OUT_RADIUS_LNG)));
      assert.ok(!/latitude/i.test(failBlob));
      assert.ok(!/longitude/i.test(failBlob));
    } finally {
      await loggingApp.close();
    }
  });
});
