import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import {
  AttendanceStatus,
  ErrorCode,
  NotificationType,
  QrTokenStatus,
  SessionStatus,
  UserRole,
} from "@wecheck/domain";
import { ctx } from "../support/e2e-context.js";
import {
  CLASS_HESD_01,
  DEFAULT_PASSWORD,
  ROOM_LAT,
  ROOM_LNG,
  SUBJECT_SWE_101,
} from "../support/constants.js";

/**
 * Flow A — Happy path workshop check-in (testing-plan §6)
 * Traceability: AC-01 AC-03 AC-04 AC-05 AC-06 AC-07 AC-13 AC-14 AC-15 AC-16
 * FR-01 FR-03 FR-04 FR-05 FR-06 FR-07 FR-12 FR-13 FR-14 FR-15 FR-16
 * BR-01 BR-05 BR-07 BR-08 BR-09 NFR-04 NFR-06 NFR-07 NFR-08
 * Cases: TC-AC-01-001 TC-AC-03-001 TC-AC-04-001 TC-AC-05-001 TC-AC-06-001
 * TC-AC-07-001 TC-AC-13-001 TC-AC-14-001 TC-AC-15-001 TC-AC-16-001
 */
describe("Flow A — happy path workshop check-in (AC-01, AC-03–AC-07, AC-13–AC-16)", () => {
  before(async () => {
    await ctx.setup();
  });

  after(async () => {
    await ctx.teardown();
  });

  it("runs full workshop lifecycle: provision → roster → session → check-in → close → export (TC-AC-01-001, TC-AC-03-001, TC-AC-04-001, TC-AC-05-001, TC-AC-06-001, TC-AC-07-001, TC-AC-13-001, TC-AC-14-001, TC-AC-15-001)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const admin = await ctx.seedAdmin();
    const instructor = await ctx.seedInstructor();

    // AC-01: Admin provisions student account
    const createRes = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/users",
      headers: { cookie: admin.cookie },
      payload: {
        institutionalId: "SV-E2E-001",
        displayName: "Nguyễn Văn E2E",
        email: "student-e2e-001@example.edu.vn",
        password: DEFAULT_PASSWORD,
        role: UserRole.Student,
      },
    });
    assert.equal(createRes.statusCode, 201);
    const created = createRes.json<{ active: boolean; institutionalId: string }>();
    assert.equal(created.active, true);
    assert.equal(created.institutionalId, "SV-E2E-001");

    const studentLogin = await ctx.login(
      "student-e2e-001@example.edu.vn",
      DEFAULT_PASSWORD,
      "/check-in?token=placeholder",
    );
    assert.ok(studentLogin.cookie);

    // AC-03: CSV roster import
    const importResult = await ctx.importRoster(admin, [
      "SV-E2E-002,Nguyễn Văn Hai,HESD-01,SWE-101",
      "SV-E2E-003,Nguyễn Văn Ba,HESD-01,SWE-101",
    ]);
    assert.equal(importResult.successRows, 2);

    await ctx.enrollStudent(studentLogin.userId);

    // AC-04: Create session with GPS in Draft
    const sessionId = await ctx.createDraftSession(instructor);
    const draft = await ctx.app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}`,
      headers: { cookie: instructor.cookie },
    });
    const draftBody = draft.json<{ status: string; roomLatitude: number; gpsRadiusMeters: number }>();
    assert.equal(draftBody.status, SessionStatus.Draft);
    assert.equal(draftBody.roomLatitude, ROOM_LAT);
    assert.equal(draftBody.gpsRadiusMeters, 100);

    // AC-05a: Open session → Active, Pending rows seeded
    await ctx.openSession(sessionId, instructor);
    const active = await ctx.app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(active.json<{ status: string }>().status, SessionStatus.Active);

    const beforeAttendance = await ctx.app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}/attendance`,
      headers: { cookie: instructor.cookie },
    });
    const beforeSummary = beforeAttendance.json<{ summary: { present: number; pending: number } }>().summary;
    const presentBefore = beforeSummary.present;

    // AC-06: Rotating QR with countdown
    const qr = await ctx.getCurrentQr(sessionId, instructor);
    assert.ok(qr.tokenId);
    assert.ok(qr.secondsRemaining > 0 && qr.secondsRemaining <= 30);

    // AC-07: Student check-in within 2s
    const start = Date.now();
    const checkInRes = await ctx.checkIn(studentLogin, qr.tokenId);
    const elapsed = Date.now() - start;
    assert.equal(checkInRes.statusCode, 200);
    assert.ok(elapsed < 5000, `check-in took ${elapsed}ms (NFR-04 p95 target 2s under normal network)`);
    const checkInBody = checkInRes.json<{
      outcome: string;
      attendance: { status: string; checkedInAt: string | null };
    }>();
    assert.equal(checkInBody.outcome, "Success");
    assert.equal(checkInBody.attendance.status, AttendanceStatus.Present);
    assert.ok(checkInBody.attendance.checkedInAt);

    const tokenRow = await ctx.db.query<{ status: string }>(
      `SELECT status FROM qr_tokens WHERE id = $1`,
      [qr.tokenId],
    );
    assert.equal(tokenRow.rows[0]?.status, QrTokenStatus.Consumed);

    // AC-15: Instructor attendance dashboard reflects Present increment
    const afterAttendance = await ctx.app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}/attendance`,
      headers: { cookie: instructor.cookie },
    });
    const afterSummary = afterAttendance.json<{
      summary: { present: number };
      records: Array<{ status: string; institutionalId: string }>;
    }>();
    assert.equal(afterSummary.summary.present, presentBefore + 1);
    const studentRow = afterSummary.records.find(
      (r) => r.institutionalId === "SV-E2E-001",
    );
    assert.equal(studentRow?.status, AttendanceStatus.Present);

    // AC-05: Close session
    await ctx.closeSession(sessionId, instructor);
    const closed = await ctx.app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(closed.json<{ status: string; closedAt: string | null }>().status, SessionStatus.Closed);
    assert.ok(closed.json<{ closedAt: string | null }>().closedAt);

    // AC-12/AC-13: Admin institution report + CSV export with audit
    const reportRes = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-01&subjectCode=SWE-101&from=2026-01-01&to=2026-12-31",
      headers: { cookie: admin.cookie },
    });
    assert.equal(reportRes.statusCode, 200);
    const reportBody = reportRes.json<{ students: unknown[]; sessionsHeld: number }>();
    assert.ok(Array.isArray(reportBody.students));
    assert.ok(reportBody.sessionsHeld >= 1);

    const exportRes = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/reports/export",
      headers: { cookie: admin.cookie },
      payload: {
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        from: "2026-01-01",
        to: "2026-12-31",
      },
    });
    assert.equal(exportRes.statusCode, 200);
    assert.match(exportRes.headers["content-type"] ?? "", /text\/csv/);
    const csv = exportRes.body;
    assert.match(csv, /institutional_id|student_id/i);
    assert.match(csv, /SV-E2E-001/);

    const auditCount = await ctx.db.query(
      `SELECT id FROM export_audit_logs WHERE admin_id = $1`,
      [admin.userId],
    );
    assert.ok((auditCount.rowCount ?? 0) >= 1);

    // AC-14: Student personal history self-scoped
    const historyRes = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/attendance/me/history?limit=20",
      headers: { cookie: studentLogin.cookie },
    });
    assert.equal(historyRes.statusCode, 200);
    const history = historyRes.json<{
      items: Array<{ status: string; checkedInAt: string | null; subject: { code: string } }>;
      totalCount: number;
    }>();
    assert.ok(history.totalCount >= 1);
    assert.ok(history.items.every((i) => i.status === AttendanceStatus.Present || i.status === AttendanceStatus.Absent));
    const presentItem = history.items.find((i) => i.status === AttendanceStatus.Present);
    assert.ok(presentItem?.checkedInAt);
    assert.equal(presentItem?.subject.code, "SWE-101");
  });

  it("instructor report scoped to assignment returns 200 (TC-AC-12-001, BR-08, FR-12)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const instructor = await ctx.seedInstructor();
    const admin = await ctx.seedAdmin();

    const reportRes = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-01&subjectCode=SWE-101&from=2026-01-01&to=2026-12-31",
      headers: { cookie: instructor.cookie },
    });
    assert.equal(reportRes.statusCode, 200);

    const deniedRes = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-02&subjectCode=SWE-102&from=2026-01-01&to=2026-12-31",
      headers: { cookie: instructor.cookie },
    });
    assert.equal(deniedRes.statusCode, 403);
    assert.equal(deniedRes.json<{ errorCode: string }>().errorCode, ErrorCode.ReportAccessDenied);

    const adminReport = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?from=2026-01-01&to=2026-12-31",
      headers: { cookie: admin.cookie },
    });
    assert.equal(adminReport.statusCode, 200);
  });

  it("session close triggers absence threshold notification when rate exceeds 20% (TC-AC-16-001, FR-16, BR-05)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const instructor = await ctx.seedInstructor();
    const student = await ctx.seedStudent("SV-THRESH-01", "thresh@example.edu.vn", "Threshold Student");
    await ctx.enrollStudent(student.userId);

    const base = new Date("2026-06-01T08:00:00.000Z");
    const statuses = [
      AttendanceStatus.Present,
      AttendanceStatus.Present,
      AttendanceStatus.Absent,
      AttendanceStatus.Present,
      AttendanceStatus.Present,
    ];
    for (let i = 0; i < 5; i++) {
      const sessionId = randomSessionId();
      await ctx.db.query(
        `INSERT INTO sessions (id, class_id, subject_id, instructor_id, title, room_name,
         room_latitude, room_longitude, gps_radius_meters, scheduled_start, status, opened_at, closed_at)
         VALUES ($1, $2, $3, $4, 'Past', 'Room', $5, $6, 100, $7, 'Closed', $7, $7)`,
        [
          sessionId,
          CLASS_HESD_01,
          SUBJECT_SWE_101,
          instructor.userId,
          ROOM_LAT,
          ROOM_LNG,
          new Date(base.getTime() + i * 86_400_000),
        ],
      );
      await ctx.db.query(
        `INSERT INTO attendance_records (id, session_id, student_id, status)
         VALUES ($1, $2, $3, $4)`,
        [randomUUID(), sessionId, student.userId, statuses[i]],
      );
    }

    const activeId = await ctx.createDraftSession(instructor);
    await ctx.openSession(activeId, instructor);

    const closeRes = await ctx.app.inject({
      method: "POST",
      url: `/api/v1/sessions/${activeId}/close`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(closeRes.statusCode, 200);

    await ctx.waitForThresholdEvaluation(activeId);

    const notes = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/notifications",
      headers: { cookie: student.cookie },
    });
    assert.equal(notes.statusCode, 200);
    const noteItems = notes.json<{ items: Array<{ type: string }> }>().items;
    assert.ok(noteItems.some((n) => n.type === NotificationType.AbsenceThresholdWarning));

    const instructorNotes = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/notifications",
      headers: { cookie: instructor.cookie },
    });
    assert.ok(
      instructorNotes.json<{ items: Array<{ type: string }> }>().items.some(
        (n) => n.type === NotificationType.AbsenceThresholdWarning,
      ),
    );
  });

  it("admin configures absence threshold policy (TC-AC-16-005, PUT /policy/absence-threshold)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const admin = await ctx.seedAdmin();
    const instructor = await ctx.seedInstructor();

    const putRes = await ctx.app.inject({
      method: "PUT",
      url: "/api/v1/policy/absence-threshold",
      headers: { cookie: admin.cookie },
      payload: { thresholdPercent: 25 },
    });
    assert.equal(putRes.statusCode, 200);
    assert.equal(putRes.json<{ thresholdPercent: number }>().thresholdPercent, 25);

    const getRes = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/policy/absence-threshold",
      headers: { cookie: admin.cookie },
    });
    assert.equal(getRes.json<{ thresholdPercent: number }>().thresholdPercent, 25);

    const denied = await ctx.app.inject({
      method: "PUT",
      url: "/api/v1/policy/absence-threshold",
      headers: { cookie: instructor.cookie },
      payload: { thresholdPercent: 15 },
    });
    assert.equal(denied.statusCode, 403);

    await ctx.app.inject({
      method: "PUT",
      url: "/api/v1/policy/absence-threshold",
      headers: { cookie: admin.cookie },
      payload: { thresholdPercent: 20 },
    });
  });
});

function randomSessionId(): string {
  return randomUUID();
}
