import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import {
  AttendanceStatus,
  ErrorCode,
  INSTRUCTOR_EDIT_WINDOW_MS,
  SessionStatus,
} from "@wecheck/domain";
import { ctx } from "../support/e2e-context.js";
import { CLASS_HESD_01, ROOM_LAT, ROOM_LNG, SUBJECT_SWE_101 } from "../support/constants.js";
import { setClock } from "../../../../apps/api/src/infra/clock.js";

/**
 * Flow C — Manual fallback and audit (testing-plan §6)
 * Traceability: AC-10 AC-11 BR-10 NFR-15 FR-11
 * Cases: TC-AC-10-002 TC-AC-11-001 TC-AC-11-002 TC-AC-11-005 TC-AC-11-006
 */
describe("Flow C — manual fallback and audit (AC-10, AC-11, BR-10, NFR-15)", () => {
  before(async () => {
    await ctx.setup();
  });

  after(async () => {
    await ctx.teardown();
  });

  async function seedClosedSessionWithPending(
    instructor: Awaited<ReturnType<typeof ctx.seedInstructor>>,
    student: Awaited<ReturnType<typeof ctx.seedStudent>>,
    closedAt = new Date("2026-06-28T10:00:00.000Z"),
  ): Promise<{ sessionId: string; recordId: string; closedAt: Date }> {
    const sessionId = randomUUID();
    await ctx.db.query(
      `INSERT INTO sessions (id, class_id, subject_id, instructor_id, title, room_name,
       room_latitude, room_longitude, gps_radius_meters, scheduled_start, status, opened_at, closed_at)
       VALUES ($1, $2, $3, $4, 'Closed Workshop', 'Room A', $5, $6, 100, $7, $8, $7, $7)`,
      [
        sessionId,
        CLASS_HESD_01,
        SUBJECT_SWE_101,
        instructor.userId,
        ROOM_LAT,
        ROOM_LNG,
        closedAt,
        SessionStatus.Closed,
      ],
    );
    const recordId = randomUUID();
    await ctx.db.query(
      `INSERT INTO attendance_records (id, session_id, student_id, status)
       VALUES ($1, $2, $3, $4)`,
      [recordId, sessionId, student.userId, AttendanceStatus.Absent],
    );
    return { sessionId, recordId, closedAt };
  }

  it("close session finalizes Pending to Absent then instructor edits within 24h (TC-AC-11-001, BR-10, FR-11)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const closedAt = new Date("2026-06-28T10:00:00.000Z");
    setClock(new Date(closedAt.getTime() + 60 * 60 * 1000));
    const instructor = await ctx.seedInstructor();
    const student = await ctx.seedStudent("SV-MANUAL-01", "manual@example.edu.vn");
    await ctx.enrollStudent(student.userId);

    const sessionId = await ctx.createDraftSession(instructor);
    await ctx.openSession(sessionId, instructor);

    const pendingBefore = await ctx.db.query<{ status: string }>(
      `SELECT status FROM attendance_records WHERE session_id = $1 AND student_id = $2`,
      [sessionId, student.userId],
    );
    assert.equal(pendingBefore.rows[0]?.status, AttendanceStatus.Pending);

    await ctx.closeSession(sessionId, instructor);

    const absentAfter = await ctx.db.query<{ status: string }>(
      `SELECT status FROM attendance_records WHERE session_id = $1 AND student_id = $2`,
      [sessionId, student.userId],
    );
    assert.equal(absentAfter.rows[0]?.status, AttendanceStatus.Absent);

    const record = await ctx.db.query<{ id: string }>(
      `SELECT id FROM attendance_records WHERE session_id = $1 AND student_id = $2`,
      [sessionId, student.userId],
    );
    const recordId = record.rows[0]!.id;

    const editRes = await ctx.app.inject({
      method: "PATCH",
      url: `/api/v1/attendance/${recordId}`,
      headers: { cookie: instructor.cookie },
      payload: { status: AttendanceStatus.Present, note: "Verified in person" },
    });
    assert.equal(editRes.statusCode, 200);
    const edited = editRes.json<{ status: string }>();
    assert.equal(edited.status, AttendanceStatus.Present);

    const audit = await ctx.db.query<{ editor_id: string; previous_status: string; new_status: string }>(
      `SELECT editor_id, previous_status, new_status FROM attendance_audit_logs WHERE attendance_record_id = $1`,
      [recordId],
    );
    assert.equal(audit.rowCount, 1);
    assert.equal(audit.rows[0]?.editor_id, instructor.userId);
    assert.equal(audit.rows[0]?.previous_status, AttendanceStatus.Absent);
    assert.equal(audit.rows[0]?.new_status, AttendanceStatus.Present);
  });

  it("instructor edit blocked after 24h; admin edit succeeds (TC-AC-11-002, TC-AC-11-006, BR-10)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const closedAt = new Date("2026-06-28T08:00:00.000Z");
    setClock(new Date(closedAt.getTime() + INSTRUCTOR_EDIT_WINDOW_MS + 60_000));

    const admin = await ctx.seedAdmin();
    const instructor = await ctx.seedInstructor();
    const student = await ctx.seedStudent("SV-MANUAL-02", "manual2@example.edu.vn");
    const { recordId } = await seedClosedSessionWithPending(instructor, student, closedAt);

    const blocked = await ctx.app.inject({
      method: "PATCH",
      url: `/api/v1/attendance/${recordId}`,
      headers: { cookie: instructor.cookie },
      payload: { status: AttendanceStatus.Present, note: "Too late" },
    });
    assert.equal(blocked.statusCode, 403);
    assert.equal(blocked.json<{ errorCode: string }>().errorCode, ErrorCode.EditWindowExpired);

    const adminEdit = await ctx.app.inject({
      method: "PATCH",
      url: `/api/v1/attendance/${recordId}`,
      headers: { cookie: admin.cookie },
      payload: { status: AttendanceStatus.Present, note: "Admin override" },
    });
    assert.equal(adminEdit.statusCode, 200);
    assert.equal(adminEdit.json<{ status: string }>().status, AttendanceStatus.Present);
  });

  it("instructor manually overrides SpoofSuspected to Present with audit (TC-AC-10-002, AC-10)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const instructor = await ctx.seedInstructor();
    const student = await ctx.seedStudent("SV-SPOOF-01", "spoof@example.edu.vn");
    await ctx.enrollStudent(student.userId);

    const sessionId = await ctx.createDraftSession(instructor);
    await ctx.openSession(sessionId, instructor);
    const qr = await ctx.getCurrentQr(sessionId, instructor);

    const spoof = await ctx.checkIn(student, qr.tokenId, {
      spoofMetadata: { mockLocationDetected: true, accuracyMeters: 1, platform: "android" },
    });
    assert.equal(spoof.statusCode, 400);
    assert.equal(spoof.json<{ outcome: string }>().outcome, ErrorCode.SpoofSuspected);

    await ctx.closeSession(sessionId, instructor);

    const record = await ctx.db.query<{ id: string; status: string }>(
      `SELECT id, status FROM attendance_records WHERE session_id = $1 AND student_id = $2`,
      [sessionId, student.userId],
    );
    const recordId = record.rows[0]!.id;
    assert.equal(record.rows[0]?.status, AttendanceStatus.Absent);

    const override = await ctx.app.inject({
      method: "PATCH",
      url: `/api/v1/attendance/${recordId}`,
      headers: { cookie: instructor.cookie },
      payload: { status: AttendanceStatus.Present, note: "Physically verified present" },
    });
    assert.equal(override.statusCode, 200);

    const audit = await ctx.db.query(
      `SELECT id FROM attendance_audit_logs WHERE attendance_record_id = $1`,
      [recordId],
    );
    assert.equal(audit.rowCount, 1);
  });

  it("check-in after session close returns SessionNotActive (TC-AC-05-004, BR-01)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const instructor = await ctx.seedInstructor();
    const student = await ctx.seedStudent("SV-CLOSED-01", "closed@example.edu.vn");
    await ctx.enrollStudent(student.userId);

    const sessionId = await ctx.createDraftSession(instructor);
    await ctx.openSession(sessionId, instructor);
    const qr = await ctx.getCurrentQr(sessionId, instructor);
    await ctx.closeSession(sessionId, instructor);

    const response = await ctx.checkIn(student, qr.tokenId);
    assert.equal(response.statusCode, 403);
    assert.equal(response.json<{ outcome: string }>().outcome, ErrorCode.SessionNotActive);

    const attendance = await ctx.db.query<{ status: string }>(
      `SELECT status FROM attendance_records WHERE session_id = $1 AND student_id = $2`,
      [sessionId, student.userId],
    );
    assert.equal(attendance.rows[0]?.status, AttendanceStatus.Absent);
  });
});
