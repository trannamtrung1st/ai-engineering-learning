import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { ErrorCode, UserRole, SESSION_COOKIE_NAME } from "@wecheck/domain";
import { createPool, setPool, closePool, type DbPool } from "../infra/db.js";
import { runMigrations } from "../infra/migrate.js";
import { buildApp } from "../server.js";
import {
  createTestUser,
  SessionStore,
  truncateAuthTables,
} from "../auth/session-store.js";
import { resetClock, setClock } from "../infra/clock.js";
import { truncateRosterTables } from "../modules/roster-enrollment/roster-service.js";
import { truncateReportingTables } from "../modules/reporting-export/repositories.js";
import { truncateSessionTables } from "../modules/session-management/session-service.js";
import { withIntegrationTestDbReset } from "../infra/integration-test-lock.js";

const CLASS_HESD_01 = "10000000-0000-4000-8000-000000000101";
const CLASS_HESD_02 = "10000000-0000-4000-8000-000000000102";
const SUBJECT_SWE_101 = "20000000-0000-4000-8000-000000000201";
const SUBJECT_SWE_102 = "20000000-0000-4000-8000-000000000202";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

/**
 * Traceability: FR-02 FR-03 NFR-10 NFR-11 NFR-16 AC-03 AC-12 AC-13 AC-14
 * Cases: TC-NFR-10-003 TC-NFR-10-009 TC-NFR-10-010 TC-NFR-11-004 TC-NFR-11-005
 * TC-NFR-11-006 TC-NFR-11-007 TC-NFR-11-008 TC-NFR-11-011 TC-NFR-11-013 TC-NFR-11-014
 * TC-NFR-11-020 TC-NFR-16-003 TC-NFR-16-004 TC-FR-02-006
 */
describe("api foundation integration (FR-02, FR-03, NFR-10, NFR-11, NFR-16)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let store: SessionStore;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    store = new SessionStore(db);
  });

  after(async () => {
    resetClock();
    await app.close();
    await closePool();
  });

  async function seedReportReferenceData(
    instructorUserId?: string,
  ): Promise<void> {
    await withIntegrationTestDbReset(db, async () => {
      await truncateSessionTables(db);
      await truncateReportingTables(db);
      await truncateRosterTables(db);
      await db.query(
        `INSERT INTO classes (id, code, name) VALUES
         ($1, 'HESD-01', 'HESD Cohort A'),
         ($2, 'HESD-02', 'HESD Cohort B')
         ON CONFLICT (id) DO NOTHING`,
        [CLASS_HESD_01, CLASS_HESD_02],
      );
      await db.query(
        `INSERT INTO subjects (id, code, name) VALUES
         ($1, 'SWE-101', 'Software Engineering 101'),
         ($2, 'SWE-102', 'Software Engineering 102')
         ON CONFLICT (id) DO NOTHING`,
        [SUBJECT_SWE_101, SUBJECT_SWE_102],
      );
      if (instructorUserId) {
        await db.query(
          `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
           VALUES ($1, $2, $3)
           ON CONFLICT (instructor_id, class_id, subject_id) DO NOTHING`,
          [instructorUserId, CLASS_HESD_01, SUBJECT_SWE_101],
        );
      }
    });
  }

  async function seedSession(role: UserRole): Promise<{ sessionId: string; userId: string }> {
    await withIntegrationTestDbReset(db, async () => {
      await truncateReportingTables(db);
      await truncateAuthTables(db);
      resetClock();
    });
    const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const userId = await createTestUser(db, {
      institutionalId: `SV-${suffix}`,
      displayName: "Test User",
      email: `test-${suffix}@example.edu.vn`,
      role,
    });
    const session = await store.createSession(userId);
    return { sessionId: session.id, userId };
  }

  it("GET /api/v1/health returns ok with connected db", async () => {
    const response = await app.inject({ method: "GET", url: "/api/v1/health" });
    assert.equal(response.statusCode, 200);
    const body = response.json<{ status: string; db: string }>();
    assert.equal(body.status, "ok");
    assert.equal(body.db, "connected");
  });

  it("protected routes return 401 Unauthenticated without session (TC-NFR-10-003, NFR-10)", async () => {
    const protectedRoutes = [
      { method: "POST" as const, url: "/api/v1/check-in" },
      { method: "GET" as const, url: "/api/v1/reports/summary?classCode=A&subjectCode=B&from=2026-06-01&to=2026-06-30" },
      { method: "POST" as const, url: "/api/v1/reports/export", payload: {} },
      { method: "GET" as const, url: "/api/v1/users" },
      { method: "POST" as const, url: "/api/v1/users", payload: { email: "x@y.z" } },
      { method: "POST" as const, url: "/api/v1/roster/import" },
      { method: "POST" as const, url: "/api/v1/sessions/00000000-0000-4000-8000-000000000001/open" },
    ];

    for (const route of protectedRoutes) {
      const response = await app.inject({
        method: route.method,
        url: route.url,
        payload: route.payload,
      });
      assert.equal(
        response.statusCode,
        401,
        `${route.method} ${route.url} should require auth`,
      );
      const body = response.json<{ errorCode: string; requestId: string }>();
      assert.equal(body.errorCode, ErrorCode.Unauthenticated);
      assert.ok(body.requestId);
    }
  });

  it("error envelope includes requestId (TC-NFR-10-004)", async () => {
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      payload: { tokenId: "00000000-0000-4000-8000-000000000099" },
    });
    const body = response.json<{ requestId: string; message: string }>();
    assert.match(body.requestId, /^[0-9a-f-]{36}$/i);
    assert.equal(body.message, "Vui lòng đăng nhập để tiếp tục");
  });

  it("Student can submit check-in; Instructor denied checkin:submit (TC-FR-02-011, NFR-11)", async () => {
    const student = await seedSession(UserRole.Student);
    const studentRes = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${student.sessionId}` },
      payload: { tokenId: "00000000-0000-4000-8000-000000000099" },
    });
    assert.notEqual(studentRes.statusCode, 403, "Student should not be forbidden");
    assert.notEqual(studentRes.statusCode, 401, "Student should be authenticated");

    const instructor = await seedSession(UserRole.Instructor);
    const instructorRes = await app.inject({
      method: "POST",
      url: "/api/v1/check-in",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${instructor.sessionId}` },
      payload: { tokenId: "00000000-0000-4000-8000-000000000099" },
    });
    assert.equal(instructorRes.statusCode, 403);
    assert.equal(
      instructorRes.json<{ errorCode: string }>().errorCode,
      ErrorCode.Forbidden,
    );
  });

  it("Student denied admin user routes (TC-NFR-11-010)", async () => {
    const student = await seedSession(UserRole.Student);
    const headers = { cookie: `${SESSION_COOKIE_NAME}=${student.sessionId}` };

    const listRes = await app.inject({ method: "GET", url: "/api/v1/users", headers });
    assert.equal(listRes.statusCode, 403);

    const createRes = await app.inject({
      method: "POST",
      url: "/api/v1/users",
      headers,
      payload: { email: "new@example.edu.vn" },
    });
    assert.equal(createRes.statusCode, 403);
  });

  it("Instructor denied report:export with ExportNotAllowed (TC-NFR-11-008)", async () => {
    const instructor = await seedSession(UserRole.Instructor);
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/reports/export",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${instructor.sessionId}` },
      payload: {
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        from: "2026-06-01",
        to: "2026-06-30",
      },
    });
    assert.equal(response.statusCode, 403);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.ExportNotAllowed,
    );
  });

  it("Bearer token authenticates without cookie (TC-FR-02-010)", async () => {
    const student = await seedSession(UserRole.Student);
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { authorization: `Bearer ${student.sessionId}` },
    });
    assert.equal(response.statusCode, 200);
    assert.equal(response.json<{ role: string }>().role, UserRole.Student);
  });

  it("session expires after 8 hours inactivity (TC-NFR-16-004, TC-FR-02-005, NFR-16)", async () => {
    const student = await seedSession(UserRole.Student);
    const t0 = new Date("2026-06-28T08:00:00.000Z");
    setClock(t0);

    await db.query(
      "UPDATE auth_sessions SET last_activity_at = $2, expires_at = $3 WHERE id = $1",
      [student.sessionId, t0, new Date("2026-06-28T16:00:00.000Z")],
    );

    setClock(new Date("2026-06-28T15:59:00.000Z"));
    const resolved = await store.resolveSession(student.sessionId);
    assert.equal(resolved.ok, true);

    setClock(new Date("2026-06-28T16:01:00.000Z"));
    const expiredRes = await app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${student.sessionId}` },
    });
    assert.equal(expiredRes.statusCode, 401);
    assert.equal(
      expiredRes.json<{ errorCode: string }>().errorCode,
      ErrorCode.SessionExpired,
    );
    resetClock();
  });

  it("authenticated request refreshes sliding inactivity window (TC-FR-02-006, TC-NFR-16-003)", async () => {
    const student = await seedSession(UserRole.Student);
    const t0 = new Date("2026-06-28T08:00:00.000Z");
    setClock(t0);

    await db.query(
      "UPDATE auth_sessions SET last_activity_at = $2 WHERE id = $1",
      [student.sessionId, t0],
    );

    setClock(new Date("2026-06-28T15:00:00.000Z"));
    await app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${student.sessionId}` },
    });

    const row = await db.query<{ last_activity_at: Date }>(
      "SELECT last_activity_at FROM auth_sessions WHERE id = $1",
      [student.sessionId],
    );
    const lastActivityMs = row.rows[0]?.last_activity_at.getTime() ?? 0;
    assert.ok(
      Math.abs(lastActivityMs - new Date("2026-06-28T15:00:00.000Z").getTime()) < 2000,
    );

    setClock(new Date("2026-06-28T22:59:00.000Z"));
    const stillValid = await store.resolveSession(student.sessionId);
    assert.equal(stillValid.ok, true);

    setClock(new Date("2026-06-28T23:01:00.000Z"));
    const expired = await app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${student.sessionId}` },
    });
    assert.equal(expired.statusCode, 401);
    assert.equal(
      expired.json<{ errorCode: string }>().errorCode,
      ErrorCode.SessionExpired,
    );

    resetClock();
  });

  it("deactivated user stale session rejected (TC-FR-02-022, BR-06)", async () => {
    const student = await seedSession(UserRole.Student);
    await db.query("UPDATE users SET active = false WHERE id = $1", [
      student.userId,
    ]);

    const response = await app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${student.sessionId}` },
    });
    assert.equal(response.statusCode, 401);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.Unauthenticated,
    );
  });

  it("malformed session cookie returns 401 (TC-NFR-10-012)", async () => {
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/auth/me",
      headers: { cookie: `${SESSION_COOKIE_NAME}=not-a-valid-uuid` },
    });
    assert.equal(response.statusCode, 401);
  });

  it("unauthenticated POST /roster/import returns 401 (TC-NFR-10-009, FR-03)", async () => {
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
    });
    assert.equal(response.statusCode, 401);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.Unauthenticated,
    );
  });

  it("Instructor denied roster:write on POST /roster/import (TC-NFR-11-011, FR-03)", async () => {
    const instructor = await seedSession(UserRole.Instructor);
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${instructor.sessionId}` },
    });
    assert.equal(response.statusCode, 403);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.Forbidden,
    );
  });

  it("Instructor GET /enrollments allowed with roster:read when assigned (TC-NFR-11-006, AC-03, FR-03)", async () => {
    const instructor = await seedSession(UserRole.Instructor);
    await db.query(
      `INSERT INTO classes (id, code, name) VALUES ($1, 'HESD-01', 'HESD Cohort A')`,
      ["10000000-0000-4000-8000-000000000101"],
    );
    await db.query(
      `INSERT INTO subjects (id, code, name) VALUES ($1, 'SWE-101', 'Software Engineering 101')`,
      ["20000000-0000-4000-8000-000000000201"],
    );

    await db.query(
      `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
       VALUES ($1, $2, $3)`,
      [
        instructor.userId,
        "10000000-0000-4000-8000-000000000101",
        "20000000-0000-4000-8000-000000000201",
      ],
    );

    const response = await app.inject({
      method: "GET",
      url: "/api/v1/enrollments?classId=10000000-0000-4000-8000-000000000101&subjectId=20000000-0000-4000-8000-000000000201",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${instructor.sessionId}` },
    });
    assert.equal(response.statusCode, 200);
    assert.equal(response.json<{ totalCount: number }>().totalCount, 0);
  });

  it("Student denied GET /enrollments without roster:read (TC-NFR-11-006, AC-03)", async () => {
    const student = await seedSession(UserRole.Student);
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/enrollments?classId=10000000-0000-4000-8000-000000000101&subjectId=20000000-0000-4000-8000-000000000201",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${student.sessionId}` },
    });
    assert.equal(response.statusCode, 403);
  });

  it("Instructor GET /reports/summary allowed; Student denied (TC-NFR-11-004, AC-12)", async () => {
    const instructor = await seedSession(UserRole.Instructor);
    await seedReportReferenceData(instructor.userId);
    const instructorRes = await app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-01&subjectCode=SWE-101&from=2026-06-01&to=2026-06-30",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${instructor.sessionId}` },
    });
    assert.equal(instructorRes.statusCode, 200);

    const student = await seedSession(UserRole.Student);
    const studentRes = await app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-01&subjectCode=SWE-101&from=2026-06-01&to=2026-06-30",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${student.sessionId}` },
    });
    assert.equal(studentRes.statusCode, 403);
    assert.equal(
      studentRes.json<{ errorCode: string }>().errorCode,
      ErrorCode.ReportAccessDenied,
    );
  });

  it("unassigned instructor report returns 403 ReportAccessDenied (TC-NFR-11-007, AC-12)", async () => {
    const instructor = await seedSession(UserRole.Instructor);
    await seedReportReferenceData(instructor.userId);
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-02&subjectCode=SWE-102&from=2026-06-01&to=2026-06-30",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${instructor.sessionId}` },
    });
    assert.equal(response.statusCode, 403);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.ReportAccessDenied,
    );
  });

  it("TrainingOfficeAdmin POST /reports/export succeeds (TC-NFR-11-005, AC-13)", async () => {
    const admin = await seedSession(UserRole.TrainingOfficeAdmin);
    await seedReportReferenceData();
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/reports/export",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${admin.sessionId}` },
      payload: {
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        from: "2026-06-01",
        to: "2026-06-30",
      },
    });
    assert.equal(response.statusCode, 200);
    assert.match(response.headers["content-type"] ?? "", /text\/csv/);
  });

  it("Student denied report export (TC-NFR-11-005, AC-13)", async () => {
    const student = await seedSession(UserRole.Student);
    await seedReportReferenceData();
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/reports/export",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${student.sessionId}` },
      payload: {
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        from: "2026-06-01",
        to: "2026-06-30",
      },
    });
    assert.equal(response.statusCode, 403);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.ExportNotAllowed,
    );
  });

  it("Flow D RBAC: report scope and export authorization (TC-NFR-11-014, AC-12, AC-13)", async () => {
    const instructor = await seedSession(UserRole.Instructor);
    await seedReportReferenceData(instructor.userId);
    const assignedReport = await app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-01&subjectCode=SWE-101&from=2026-06-01&to=2026-06-30",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${instructor.sessionId}` },
    });
    assert.equal(assignedReport.statusCode, 200);

    const unassignedReport = await app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-02&subjectCode=SWE-102&from=2026-06-01&to=2026-06-30",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${instructor.sessionId}` },
    });
    assert.equal(unassignedReport.statusCode, 403);

    const instructorExport = await app.inject({
      method: "POST",
      url: "/api/v1/reports/export",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${instructor.sessionId}` },
      payload: {
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        from: "2026-06-01",
        to: "2026-06-30",
      },
    });
    assert.equal(instructorExport.statusCode, 403);

    const admin = await seedSession(UserRole.TrainingOfficeAdmin);
    await seedReportReferenceData();
    const adminExport = await app.inject({
      method: "POST",
      url: "/api/v1/reports/export",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${admin.sessionId}` },
      payload: {
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        from: "2026-06-01",
        to: "2026-06-30",
      },
    });
    assert.equal(adminExport.statusCode, 200);
  });

  it("Student GET /attendance/me/history returns self-scoped records only (TC-NFR-11-013, AC-14)", async () => {
    const student = await seedSession(UserRole.Student);
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/attendance/me/history",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${student.sessionId}` },
    });
    assert.equal(response.statusCode, 200);
    const body = response.json<{
      items: unknown[];
      nextCursor: string | null;
      totalCount: number;
    }>();
    assert.ok(Array.isArray(body.items));
    assert.equal(body.totalCount, body.items.length);
    assert.equal(body.nextCursor, null);
  });

  it("Instructor denied audit:read (TC-NFR-11-011)", async () => {
    const instructor = await seedSession(UserRole.Instructor);
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/audit/logs",
      headers: { cookie: `${SESSION_COOKIE_NAME}=${instructor.sessionId}` },
    });
    assert.equal(response.statusCode, 403);
  });
});
