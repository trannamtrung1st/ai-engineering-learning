import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import {
  AttendanceStatus,
  ErrorCode,
  QR_TOKEN_TTL_MS,
  QrTokenStatus,
  UserRole,
} from "@wecheck/domain";
import { ctx } from "../support/e2e-context.js";
import {
  DEFAULT_PASSWORD,
  IN_RADIUS_LAT,
  IN_RADIUS_LNG,
  OUT_RADIUS_LAT,
  OUT_RADIUS_LNG,
} from "../support/constants.js";
import { advanceClock } from "../../../../apps/api/src/infra/clock.js";

/**
 * Flow B — Anti-fraud rejection paths (testing-plan §6)
 * Traceability: AC-02 AC-06 AC-08 AC-09 AC-10
 * FR-02 FR-06 FR-08 FR-09 FR-10 BR-02 BR-03 BR-04 BR-06 BR-11 BR-12 NFR-02 NFR-12
 * Cases: TC-AC-02-001 TC-AC-06-002 TC-AC-08-002 TC-AC-09-001 TC-AC-09-002 TC-AC-10-001
 */
describe("Flow B — anti-fraud rejection paths (AC-02, AC-06, AC-08–AC-10)", () => {
  before(async () => {
    await ctx.setup();
  });

  after(async () => {
    await ctx.teardown();
  });

  async function seedActiveWorkshop(): Promise<{
    sessionId: string;
    instructor: Awaited<ReturnType<typeof ctx.seedInstructor>>;
    studentA: Awaited<ReturnType<typeof ctx.seedStudent>>;
    studentB: Awaited<ReturnType<typeof ctx.seedStudent>>;
    studentC: Awaited<ReturnType<typeof ctx.seedStudent>>;
    tokenId: string;
  }> {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const instructor = await ctx.seedInstructor();
    const studentA = await ctx.seedStudent("SV-FRAUD-A", "fraud-a@example.edu.vn", "Student A");
    const studentB = await ctx.seedStudent("SV-FRAUD-B", "fraud-b@example.edu.vn", "Student B");
    const studentC = await ctx.seedStudent("SV-FRAUD-C", "fraud-c@example.edu.vn", "Student C");
    await ctx.enrollStudent(studentA.userId);
    await ctx.enrollStudent(studentB.userId);
    const sessionId = await ctx.createDraftSession(instructor);
    await ctx.openSession(sessionId, instructor);
    const qr = await ctx.getCurrentQr(sessionId, instructor);
    return { sessionId, instructor, studentA, studentB, studentC, tokenId: qr.tokenId };
  }

  it("unauthenticated POST /check-in returns 401 Unauthenticated (TC-AC-02-001, BR-06, FR-02)", async () => {
    const { tokenId } = await seedActiveWorkshop();
    const response = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      payload: ctx.checkInPayload(tokenId),
    });
    assert.equal(response.statusCode, 401);
    const body = response.json<{ errorCode: string; message: string }>();
    assert.equal(body.errorCode, ErrorCode.Unauthenticated);
    assert.equal(body.message, "Vui lòng đăng nhập để tiếp tục");
  });

  it("login with returnUrl preserves check-in deep link (TC-AC-02-002, FR-02)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const student = await ctx.seedStudent("SV-RETURL", "returl@example.edu.vn");
    const returnUrl = "/check-in?token=00000000-0000-4000-8000-000000000099";
    const login = await ctx.login(student.email!, DEFAULT_PASSWORD, returnUrl);
    const me = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: login.cookie },
    });
    assert.equal(me.statusCode, 200);
    assert.equal(me.json<{ role: string }>().role, UserRole.Student);
  });

  it("student A success then duplicate check-in returns 409 DuplicateCheckIn (TC-AC-09-001, BR-04)", async () => {
    const { sessionId, instructor, studentA, tokenId } = await seedActiveWorkshop();

    const first = await ctx.checkIn(studentA, tokenId);
    assert.equal(first.statusCode, 200);

    const freshQr = await ctx.getCurrentQr(sessionId, instructor);
    const duplicate = await ctx.checkIn(studentA, freshQr.tokenId);
    assert.equal(duplicate.statusCode, 409);
    const dupBody = duplicate.json<{ outcome: string; errorCode: string; message: string }>();
    assert.equal(dupBody.outcome, ErrorCode.DuplicateCheckIn);
    assert.equal(dupBody.errorCode, ErrorCode.DuplicateCheckIn);
    assert.match(dupBody.message, /đã điểm danh/i);
  });

  it("same token used by second student is rejected with security log (TC-AC-09-002, BR-11)", async () => {
    const { sessionId, studentA, studentB, tokenId } = await seedActiveWorkshop();

    const first = await ctx.checkIn(studentA, tokenId);
    assert.equal(first.statusCode, 200);

    const second = await ctx.checkIn(studentB, tokenId);
    assert.notEqual(second.statusCode, 200);
    const body = second.json<{ outcome: string }>();
    assert.ok(
      body.outcome === ErrorCode.TokenAlreadyUsed || body.outcome === ErrorCode.ExpiredQr,
    );

    const audit = await ctx.db.query(
      `SELECT id FROM security_audit_logs
       WHERE session_id = $1 AND event_type = 'TokenReuseAlert'`,
      [sessionId],
    );
    assert.ok((audit.rowCount ?? 0) >= 1);
  });

  it("student outside GPS radius gets OutOfRadius (TC-AC-08-002, BR-02, FR-08)", async () => {
    const { sessionId, studentA, tokenId } = await seedActiveWorkshop();

    const response = await ctx.checkIn(studentA, tokenId, {
      latitude: OUT_RADIUS_LAT,
      longitude: OUT_RADIUS_LNG,
    });
    assert.equal(response.statusCode, 400);
    const body = response.json<{ outcome: string; errorCode: string }>();
    assert.equal(body.outcome, ErrorCode.OutOfRadius);

    const attendance = await ctx.db.query<{ status: string }>(
      `SELECT status FROM attendance_records WHERE session_id = $1 AND student_id = $2`,
      [sessionId, studentA.userId],
    );
    assert.equal(attendance.rows[0]?.status, AttendanceStatus.Pending);
  });

  it("expired QR token after 31 seconds returns ExpiredQr (TC-AC-06-002, BR-03)", async () => {
    const { studentA, tokenId } = await seedActiveWorkshop();

    advanceClock(QR_TOKEN_TTL_MS + 1000);

    const response = await ctx.checkIn(studentA, tokenId);
    assert.equal(response.statusCode, 400);
    const body = response.json<{ outcome: string; message: string }>();
    assert.equal(body.outcome, ErrorCode.ExpiredQr);
    assert.match(body.message, /hết hạn/i);

    const token = await ctx.db.query<{ status: string }>(
      `SELECT status FROM qr_tokens WHERE id = $1`,
      [tokenId],
    );
    assert.notEqual(token.rows[0]?.status, QrTokenStatus.Consumed);
  });

  it("not enrolled student check-in rejected (TC-AC-07-002, FR-07)", async () => {
    const { sessionId, studentC, tokenId } = await seedActiveWorkshop();

    const response = await ctx.checkIn(studentC, tokenId);
    assert.equal(response.statusCode, 403);
    const body = response.json<{ outcome: string; errorCode: string }>();
    assert.equal(body.outcome, ErrorCode.NotEnrolled);

    const attendance = await ctx.db.query(
      `SELECT id FROM attendance_records WHERE session_id = $1 AND student_id = $2 AND status = 'Present'`,
      [sessionId, studentC.userId],
    );
    assert.equal(attendance.rowCount, 0);
  });

  it("mock location flagged as SpoofSuspected (TC-AC-10-001, FR-10)", async () => {
    const { sessionId, studentA, tokenId } = await seedActiveWorkshop();

    const response = await ctx.checkIn(studentA, tokenId, {
      spoofMetadata: { mockLocationDetected: true, accuracyMeters: 1, platform: "android" },
    });
    assert.equal(response.statusCode, 400);
    const body = response.json<{ outcome: string }>();
    assert.equal(body.outcome, ErrorCode.SpoofSuspected);

    const security = await ctx.db.query(
      `SELECT id FROM security_audit_logs WHERE session_id = $1`,
      [sessionId],
    );
    assert.ok((security.rowCount ?? 0) >= 1);
  });

  it("GPS within radius passes radius check (TC-AC-08-001, BR-02)", async () => {
    const { studentA, tokenId } = await seedActiveWorkshop();

    const response = await ctx.checkIn(studentA, tokenId, {
      latitude: IN_RADIUS_LAT,
      longitude: IN_RADIUS_LNG,
    });
    assert.equal(response.statusCode, 200);

    const columns = await ctx.db.query<{ column_name: string }>(
      `SELECT column_name FROM information_schema.columns
       WHERE table_name = 'attendance_records' AND column_name ILIKE '%lat%'`,
    );
    assert.equal(columns.rowCount, 0);
  });

  it("instructor denied POST /check-in (TC-AC-02-006, NFR-11)", async () => {
    const { instructor, tokenId } = await seedActiveWorkshop();

    const response = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: instructor.cookie },
      payload: ctx.checkInPayload(tokenId),
    });
    assert.equal(response.statusCode, 403);
  });
});
