import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { ErrorCode, UserRole } from "@wecheck/domain";
import { ctx } from "../support/e2e-context.js";
import { CLASS_HESD_01, CLASS_HESD_02, DEFAULT_PASSWORD, SUBJECT_SWE_101 } from "../support/constants.js";
import { buildCsv, multipartPayload } from "../support/multipart.js";

/**
 * Flow D — Reporting authorization (testing-plan §6)
 * Traceability: AC-01 AC-02 AC-03 AC-12 AC-13 AC-14
 * FR-01 FR-02 FR-03 FR-04 FR-06 FR-12 FR-13 FR-14 BR-06 BR-08 BR-09 BR-14 NFR-07 NFR-10 NFR-11 NFR-15
 * Cases: TC-AC-01-004 TC-AC-01-005 TC-AC-03-004 TC-AC-03-006 TC-AC-12-003
 * TC-AC-13-002 TC-AC-14-003 TC-AC-14-005 TC-NFR-07-013 TC-NFR-10-009 TC-NFR-11-004
 * TC-NFR-11-005 TC-NFR-11-006 TC-NFR-11-007 TC-NFR-11-008 TC-NFR-11-012
 * TC-NFR-11-013 TC-NFR-11-014
 */
describe("Flow D — reporting authorization (AC-01, AC-02, AC-03, AC-12–AC-14)", () => {
  before(async () => {
    await ctx.setup();
  });

  after(async () => {
    await ctx.teardown();
  });

  it("duplicate institutionalId rejected with 422 (TC-AC-01-004, FR-01)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const admin = await ctx.seedAdmin();

    const first = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/users",
      headers: { cookie: admin.cookie },
      payload: {
        institutionalId: "SV-DUP-001",
        displayName: "First Student",
        email: "dup-first@example.edu.vn",
        password: DEFAULT_PASSWORD,
        role: UserRole.Student,
      },
    });
    assert.equal(first.statusCode, 201);

    const duplicate = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/users",
      headers: { cookie: admin.cookie },
      payload: {
        institutionalId: "SV-DUP-001",
        displayName: "Duplicate Student",
        email: "dup-second@example.edu.vn",
        password: DEFAULT_PASSWORD,
        role: UserRole.Student,
      },
    });
    assert.equal(duplicate.statusCode, 422);
    assert.equal(duplicate.json<{ errorCode: string }>().errorCode, ErrorCode.ValidationFailed);

    const count = await ctx.db.query(
      `SELECT id FROM users WHERE institutional_id = $1`,
      ["SV-DUP-001"],
    );
    assert.equal(count.rowCount, 1);
  });

  it("deactivated user login fails with AccountDeactivated (TC-AC-01-005, BR-06)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const admin = await ctx.seedAdmin();

    const create = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/users",
      headers: { cookie: admin.cookie },
      payload: {
        institutionalId: "SV-DEACT-01",
        displayName: "Deactivated Student",
        email: "deact@example.edu.vn",
        password: DEFAULT_PASSWORD,
        role: UserRole.Student,
      },
    });
    const userId = create.json<{ id: string }>().id;

    const deactivate = await ctx.app.inject({
      method: "PATCH",
      url: `/api/v1/users/${userId}`,
      headers: { cookie: admin.cookie },
      payload: { active: false },
    });
    assert.equal(deactivate.statusCode, 200);

    const login = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email: "deact@example.edu.vn", password: DEFAULT_PASSWORD },
    });
    assert.equal(login.statusCode, 403);
    assert.equal(login.json<{ errorCode: string }>().errorCode, ErrorCode.AccountDeactivated);
  });

  it("unauthenticated POST /roster/import returns 401 (TC-NFR-10-009, FR-03)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));

    const response = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
    });
    assert.equal(response.statusCode, 401);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.Unauthenticated,
    );
  });

  it("instructor denied unassigned roster with 403 (TC-AC-03-006, TC-NFR-11-006, BR-08, FR-03, AC-03)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const admin = await ctx.seedAdmin();
    const instructor = await ctx.seedInstructor(true);

    await ctx.importRoster(admin, [
      "SV-ROSTER-01,Nguyễn A,HESD-02,SWE-101",
    ]);

    const denied = await ctx.app.inject({
      method: "GET",
      url: `/api/v1/enrollments?classId=${CLASS_HESD_02}&subjectId=${SUBJECT_SWE_101}`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(denied.statusCode, 403);
    assert.equal(denied.json<{ errorCode: string }>().errorCode, ErrorCode.Forbidden);

    const allowed = await ctx.app.inject({
      method: "GET",
      url: `/api/v1/enrollments?classId=${CLASS_HESD_01}&subjectId=${SUBJECT_SWE_101}`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(allowed.statusCode, 200);
  });

  it("instructor denied CSV export; admin export audit-logged (TC-AC-13-002, TC-NFR-11-005, TC-NFR-11-008, TC-NFR-11-011, AC-13, BR-09, FR-13)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const admin = await ctx.seedAdmin();
    const instructor = await ctx.seedInstructor();

    const denied = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/reports/export",
      headers: { cookie: instructor.cookie },
      payload: {
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        from: "2026-01-01",
        to: "2026-12-31",
      },
    });
    assert.equal(denied.statusCode, 403);
    const deniedBody = denied.json<{ errorCode: string; message: string }>();
    assert.equal(deniedBody.errorCode, ErrorCode.ExportNotAllowed);
    assert.match(deniedBody.message, /phòng đào tạo/i);

    const securityBefore = await ctx.db.query(
      `SELECT id FROM security_audit_logs WHERE event_type = 'ExportDenied'`,
    );
    const beforeCount = securityBefore.rowCount ?? 0;

    const deniedAgain = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/reports/export",
      headers: { cookie: instructor.cookie },
      payload: {
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        from: "2026-01-01",
        to: "2026-12-31",
      },
    });
    assert.equal(deniedAgain.statusCode, 403);

    const securityAfter = await ctx.db.query(
      `SELECT id FROM security_audit_logs WHERE event_type = 'ExportDenied'`,
    );
    assert.ok((securityAfter.rowCount ?? 0) > beforeCount);

    const exportOk = await ctx.app.inject({
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
    assert.equal(exportOk.statusCode, 200);

    const exportAudit = await ctx.db.query(
      `SELECT id FROM export_audit_logs WHERE admin_id = $1`,
      [admin.userId],
    );
    assert.ok((exportAudit.rowCount ?? 0) >= 1);
  });

  it("student denied session roster and peer PATCH (TC-AC-14-003, TC-AC-14-005, TC-NFR-11-013, AC-14, FR-14)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const instructor = await ctx.seedInstructor();
    const studentA = await ctx.seedStudent("SV-PEER-A", "peer-a@example.edu.vn");
    const studentB = await ctx.seedStudent("SV-PEER-B", "peer-b@example.edu.vn");
    await ctx.enrollStudent(studentA.userId);
    await ctx.enrollStudent(studentB.userId);

    const sessionId = await ctx.createDraftSession(instructor);
    await ctx.openSession(sessionId, instructor);
    await ctx.closeSession(sessionId, instructor);

    const rosterDenied = await ctx.app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}/attendance`,
      headers: { cookie: studentA.cookie },
    });
    assert.equal(rosterDenied.statusCode, 403);
    assert.equal(rosterDenied.json<{ errorCode: string }>().errorCode, ErrorCode.Forbidden);

    const peerRecord = await ctx.db.query<{ id: string }>(
      `SELECT id FROM attendance_records WHERE session_id = $1 AND student_id = $2`,
      [sessionId, studentB.userId],
    );
    const patchDenied = await ctx.app.inject({
      method: "PATCH",
      url: `/api/v1/attendance/${peerRecord.rows[0]!.id}`,
      headers: { cookie: studentA.cookie },
      payload: { status: "Present", note: "Unauthorized" },
    });
    assert.equal(patchDenied.statusCode, 403);

    const unauthHistory = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/attendance/me/history",
    });
    assert.equal(unauthHistory.statusCode, 401);
    assert.equal(unauthHistory.json<{ errorCode: string }>().errorCode, ErrorCode.Unauthenticated);
  });

  it("CSV import partial duplicate row rejects duplicate keeps valid (TC-AC-03-004, FR-03)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const admin = await ctx.seedAdmin();

    await ctx.importRoster(admin, ["SV-CSV-01,Nguyễn Một,HESD-01,SWE-101"]);

    const csv = buildCsv([
      "SV-CSV-01,Nguyễn Một,HESD-01,SWE-101",
      "SV-CSV-02,Nguyễn Hai,HESD-01,SWE-101",
    ]);
    const { payload, contentType } = multipartPayload(csv);
    const importRes = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
      headers: { cookie: admin.cookie, "content-type": contentType },
      payload,
    });
    assert.equal(importRes.statusCode, 202);
    const { batchId } = importRes.json<{ batchId: string }>();

    let successRows = 0;
    let errorRows = 0;
    for (let i = 0; i < 30; i += 1) {
      const poll = await ctx.app.inject({
        method: "GET",
        url: `/api/v1/roster/imports/${batchId}`,
        headers: { cookie: admin.cookie },
      });
      const body = poll.json<{ status: string; successRows: number; errorRows: number }>();
      if (body.status === "Completed" || body.status === "Failed") {
        successRows = body.successRows;
        errorRows = body.errorRows;
        break;
      }
      await new Promise((r) => setTimeout(r, 50));
    }
    assert.equal(successRows, 1);
    assert.equal(errorRows, 1);
  });

  it("instructor report denied for unassigned class (TC-AC-12-003, TC-NFR-11-004, TC-NFR-11-007, TC-NFR-11-014, AC-12, BR-08, FR-12)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const instructor = await ctx.seedInstructor(true);

    const denied = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-02&subjectCode=SWE-102&from=2026-01-01&to=2026-12-31",
      headers: { cookie: instructor.cookie },
    });
    assert.equal(denied.statusCode, 403);
  });

  it("student denied report endpoints immediately; instructor session report within NFR-07 (TC-NFR-07-013, BR-14, NFR-07, NFR-11, FR-12)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const instructor = await ctx.seedInstructor();
    const student = await ctx.seedStudent("SV-RPT-DENY", "report-deny@example.edu.vn");
    const studentB = await ctx.seedStudent("SV-RPT-PEER", "report-peer@example.edu.vn");
    await ctx.enrollStudent(student.userId);
    await ctx.enrollStudent(studentB.userId);

    const sessionId = await ctx.createDraftSession(instructor);
    await ctx.openSession(sessionId, instructor);
    await ctx.closeSession(sessionId, instructor);

    const sessionDeniedStart = performance.now();
    const sessionDenied = await ctx.app.inject({
      method: "GET",
      url: `/api/v1/reports/session/${sessionId}`,
      headers: { cookie: student.cookie },
    });
    const sessionDeniedElapsed = performance.now() - sessionDeniedStart;
    assert.equal(sessionDenied.statusCode, 403);
    assert.equal(
      sessionDenied.json<{ errorCode: string }>().errorCode,
      ErrorCode.ReportAccessDenied,
    );
    assert.ok(
      sessionDeniedElapsed < 5000,
      `student session report denial took ${sessionDeniedElapsed.toFixed(1)}ms`,
    );
    assert.equal(sessionDenied.json<{ records?: unknown }>().records, undefined);

    const summaryDeniedStart = performance.now();
    const summaryDenied = await ctx.app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-01&subjectCode=SWE-101&from=2026-01-01&to=2026-12-31",
      headers: { cookie: student.cookie },
    });
    const summaryDeniedElapsed = performance.now() - summaryDeniedStart;
    assert.equal(summaryDenied.statusCode, 403);
    assert.equal(
      summaryDenied.json<{ errorCode: string; message: string }>().errorCode,
      ErrorCode.ReportAccessDenied,
    );
    assert.match(
      summaryDenied.json<{ message: string }>().message,
      /quyền xem báo cáo/i,
    );
    assert.ok(
      summaryDeniedElapsed < 5000,
      `student summary report denial took ${summaryDeniedElapsed.toFixed(1)}ms`,
    );

    const closedAt = await ctx.db.query<{ closed_at: Date }>(
      `SELECT closed_at FROM sessions WHERE id = $1`,
      [sessionId],
    );
    const closedAtMs = closedAt.rows[0]!.closed_at.getTime();

    const instructorReportStart = performance.now();
    const instructorReport = await ctx.app.inject({
      method: "GET",
      url: `/api/v1/reports/session/${sessionId}`,
      headers: { cookie: instructor.cookie },
    });
    const instructorReportElapsed = performance.now() - instructorReportStart;
    assert.equal(instructorReport.statusCode, 200);
    const reportBody = instructorReport.json<{
      summary: { present: number; absent: number; pending: number };
      records: Array<{ status: string }>;
    }>();
    assert.equal(reportBody.summary.pending, 0);
    assert.equal(reportBody.records.length, 2);
    assert.ok(
      instructorReportElapsed <= 600_000,
      `instructor report took ${instructorReportElapsed.toFixed(1)}ms (NFR-07 budget 600000ms)`,
    );
    assert.ok(
      Date.now() - closedAtMs <= 600_000,
      "instructor report available within 10 minutes of closedAt",
    );
  });

  it("student denied session management and qr:display (TC-NFR-11-012, FR-04, FR-06)", async () => {
    await ctx.resetDb(ctx.seedReferenceData.bind(ctx));
    const instructor = await ctx.seedInstructor();
    const student = await ctx.seedStudent("SV-SESS-RBAC", "sess-rbac@example.edu.vn");
    const sessionId = await ctx.createDraftSession(instructor);
    await ctx.openSession(sessionId, instructor);

    const createDenied = await ctx.app.inject({
      method: "POST",
      url: "/api/v1/sessions",
      headers: { cookie: student.cookie },
      payload: {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Student Session",
        roomName: "Phòng A201",
        scheduledStart: ctx.futureStart(),
      },
    });
    assert.equal(createDenied.statusCode, 403);
    assert.equal(createDenied.json<{ errorCode: string }>().errorCode, ErrorCode.Forbidden);

    const openDenied = await ctx.app.inject({
      method: "POST",
      url: `/api/v1/sessions/${sessionId}/open`,
      headers: { cookie: student.cookie },
    });
    assert.equal(openDenied.statusCode, 403);
    assert.equal(openDenied.json<{ errorCode: string }>().errorCode, ErrorCode.Forbidden);

    const qrDenied = await ctx.app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}/qr/current`,
      headers: { cookie: student.cookie },
    });
    assert.equal(qrDenied.statusCode, 403);
    assert.equal(qrDenied.json<{ errorCode: string }>().errorCode, ErrorCode.Forbidden);
  });
});
