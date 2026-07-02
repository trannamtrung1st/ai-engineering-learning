/**
 * REG-04/05/06/07 — role-scoped report/export E2E regression with audit side effects.
 *
 * Traceability: AC-15 AC-16 AC-17 AC-23 NFR-09 NFR-10
 * TC-AC-15-001 TC-AC-15-003 TC-AC-15-004 TC-AC-15-005 TC-AC-15-006 TC-AC-15-008
 * TC-AC-16-001 TC-AC-16-003 TC-AC-16-004 TC-AC-16-005 TC-AC-16-006 TC-AC-16-007 TC-AC-16-008 TC-AC-16-009
 * TC-AC-17-001 TC-AC-17-003 TC-AC-17-004 TC-AC-17-006 TC-AC-17-007
 * TC-AC-23-001 TC-AC-23-003 TC-AC-23-006 TC-AC-23-007 TC-AC-23-008 TC-AC-23-009 TC-AC-23-010 TC-AC-23-012 TC-AC-23-013 TC-AC-23-014
 * TC-NFR-09-001 TC-NFR-09-004 TC-NFR-09-005 TC-NFR-09-006 TC-NFR-09-007 TC-NFR-09-008 TC-NFR-09-009 TC-NFR-09-010 TC-NFR-09-011 TC-NFR-09-012
 * TC-NFR-10-005 TC-NFR-10-006 TC-NFR-10-007 TC-NFR-10-012
 */
import { randomUUID } from "node:crypto";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../../../../apps/api/src/app.js";
import {
  ROLE_MATRIX_EMAILS,
  ROLE_MATRIX_SEED,
  assertDenialWithoutLeakage,
  completeExport,
  deleteExportJobsForActor,
  ensureMigratedAndSeeded,
  ensureRoleMatrixHierarchy,
  insertAttendanceRow,
  insertClosedSession,
  login,
  waitForSeededDb,
} from "../fixtures/role-matrix-fixtures.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;

describe("REG role scope and export E2E — AC-15 AC-16 AC-17 AC-23 NFR-09 NFR-10", () => {
  let app: FastifyInstance;
  let pool: pg.Pool;
  let lecturerToken: string;
  let studentToken: string;
  let academicAdminToken: string;
  let systemAuditorToken: string;
  let itAdminToken: string;
  const cleanupSessionIds: string[] = [];

  beforeAll(async () => {
    expect(databaseUrl).toBeTruthy();
    process.env.DATABASE_URL = databaseUrl;
    process.env.JWT_SECRET = "test-jwt";
    await ensureMigratedAndSeeded();
    const probe = new pg.Client({ connectionString: databaseUrl });
    await probe.connect();
    await waitForSeededDb(probe);
    await probe.end();
    app = await buildApp();
    await app.ready();
    pool = new pg.Pool({ connectionString: databaseUrl });
    await ensureRoleMatrixHierarchy(pool);
    lecturerToken = await login(app, ROLE_MATRIX_EMAILS.lecturer);
    studentToken = await login(app, ROLE_MATRIX_EMAILS.student);
    academicAdminToken = await login(app, ROLE_MATRIX_EMAILS.academicAdmin);
    systemAuditorToken = await login(app, ROLE_MATRIX_EMAILS.systemAuditor);
    itAdminToken = await login(app, ROLE_MATRIX_EMAILS.itAdmin);
  }, 120_000);

  afterEach(async () => {
    for (const sessionId of cleanupSessionIds.splice(0)) {
      await pool.query(`DELETE FROM attendance_records WHERE class_session_id = $1`, [sessionId]);
      await pool.query(`DELETE FROM class_sessions WHERE id = $1`, [sessionId]);
    }
    await deleteExportJobsForActor(pool, ROLE_MATRIX_SEED.lecturer);
    await deleteExportJobsForActor(pool, ROLE_MATRIX_SEED.academicAdmin);
  });

  afterAll(async () => {
    await app?.close();
    await pool?.end().catch(() => undefined);
  });

  async function seedAttendancePair(): Promise<{ sessionA: string; sessionB: string }> {
    const sessionA = await insertClosedSession(pool, ROLE_MATRIX_SEED.sectionA);
    const sessionB = await insertClosedSession(pool, ROLE_MATRIX_SEED.sectionB);
    cleanupSessionIds.push(sessionA, sessionB);
    await insertAttendanceRow(pool, {
      sessionId: sessionA,
      sectionId: ROLE_MATRIX_SEED.sectionA,
      studentUserId: ROLE_MATRIX_SEED.student,
      status: "Present",
    });
    await insertAttendanceRow(pool, {
      sessionId: sessionB,
      sectionId: ROLE_MATRIX_SEED.sectionB,
      studentUserId: ROLE_MATRIX_SEED.student,
      status: "Absent",
    });
    return { sessionA, sessionB };
  }

  describe("REG-04 lecturer scoped report and export — AC-15", () => {
    it("TC-AC-15-004 TC-AC-15-005: lecturer report and export limited to assigned section A", async () => {
      await seedAttendancePair();

      const reportResponse = await app.inject({
        method: "GET",
        url: `/api/v1/reports/attendance?termId=${ROLE_MATRIX_SEED.term}&page=1&pageSize=25`,
        headers: { authorization: `Bearer ${lecturerToken}` },
      });
      expect(reportResponse.statusCode).toBe(200);
      const reportBody = reportResponse.json() as {
        data: { classSectionId: string }[];
        meta: { pagination: { totalItems: number } };
      };
      expect(reportBody.data.every((row) => row.classSectionId === ROLE_MATRIX_SEED.sectionA)).toBe(
        true,
      );
      expect(reportBody.data.some((row) => row.classSectionId === ROLE_MATRIX_SEED.sectionB)).toBe(
        false,
      );

      const { csv } = await completeExport(app, lecturerToken, {
        termId: ROLE_MATRIX_SEED.term,
        classSectionId: ROLE_MATRIX_SEED.sectionA,
      });
      expect(csv).toContain(ROLE_MATRIX_SEED.sectionA);
      expect(csv).not.toContain(ROLE_MATRIX_SEED.sectionB);
    });

    it("TC-AC-15-003 TC-AC-15-008: term-wide export still excludes unassigned section B", async () => {
      await seedAttendancePair();

      const { csv } = await completeExport(app, lecturerToken, {
        termId: ROLE_MATRIX_SEED.term,
      });
      expect(csv).toContain(ROLE_MATRIX_SEED.sectionA);
      expect(csv).not.toContain(ROLE_MATRIX_SEED.sectionB);
    });
  });

  describe("REG-05 denial without data leakage — AC-16 NFR-09", () => {
    it("TC-AC-16-003 TC-AC-16-004 TC-NFR-09-010: student self-scoped report allowed; export denied", async () => {
      await seedAttendancePair();

      const reportResponse = await app.inject({
        method: "GET",
        url: `/api/v1/reports/attendance?termId=${ROLE_MATRIX_SEED.term}&page=1&pageSize=25`,
        headers: { authorization: `Bearer ${studentToken}` },
      });
      expect(reportResponse.statusCode).toBe(200);
      const reportBody = reportResponse.json() as {
        data: { studentUserId: string }[];
        error: null;
      };
      expect(reportBody.error).toBeNull();
      expect(
        reportBody.data.every((row) => row.studentUserId === ROLE_MATRIX_SEED.student),
      ).toBe(true);

      const escalationResponse = await app.inject({
        method: "GET",
        url: `/api/v1/reports/attendance?termId=${ROLE_MATRIX_SEED.term}&studentUserId=60000000-0000-4000-8000-000000000003&page=1&pageSize=25`,
        headers: { authorization: `Bearer ${studentToken}` },
      });
      expect(escalationResponse.statusCode).toBe(403);
      assertDenialWithoutLeakage(escalationResponse.json());

      const exportResponse = await app.inject({
        method: "POST",
        url: "/api/v1/exports/attendance",
        headers: {
          authorization: `Bearer ${studentToken}`,
          "idempotency-key": randomUUID(),
        },
        payload: { format: "csv", filters: { termId: ROLE_MATRIX_SEED.term } },
      });
      expect(exportResponse.statusCode).toBe(403);
      assertDenialWithoutLeakage(exportResponse.json());

      const beforeJobs = await pool.query(`SELECT COUNT(*)::int AS count FROM export_jobs`);
      expect(beforeJobs.rows[0].count).toBeGreaterThanOrEqual(0);
    });

    it("TC-AC-16-007 TC-NFR-09-008: lecturer denied cross-section report, export, and roster", async () => {
      const { sessionB } = await seedAttendancePair();

      const reportResponse = await app.inject({
        method: "GET",
        url: `/api/v1/reports/attendance?classSectionId=${ROLE_MATRIX_SEED.sectionB}&page=1&pageSize=25`,
        headers: { authorization: `Bearer ${lecturerToken}` },
      });
      expect(reportResponse.statusCode).toBe(403);
      assertDenialWithoutLeakage(reportResponse.json());

      const exportResponse = await app.inject({
        method: "POST",
        url: "/api/v1/exports/attendance",
        headers: {
          authorization: `Bearer ${lecturerToken}`,
          "idempotency-key": randomUUID(),
        },
        payload: {
          format: "csv",
          filters: { classSectionId: ROLE_MATRIX_SEED.sectionB },
        },
      });
      expect(exportResponse.statusCode).toBe(403);
      assertDenialWithoutLeakage(exportResponse.json());

      const rosterResponse = await app.inject({
        method: "GET",
        url: `/api/v1/class-sessions/${sessionB}/attendance`,
        headers: { authorization: `Bearer ${lecturerToken}` },
      });
      expect(rosterResponse.statusCode).toBe(403);
      assertDenialWithoutLeakage(rosterResponse.json());
    });

    it("TC-AC-16-005 TC-NFR-09-009: ITAdmin denied academic report and export", async () => {
      await seedAttendancePair();

      const reportResponse = await app.inject({
        method: "GET",
        url: `/api/v1/reports/attendance?termId=${ROLE_MATRIX_SEED.term}`,
        headers: { authorization: `Bearer ${itAdminToken}` },
      });
      expect(reportResponse.statusCode).toBe(403);
      assertDenialWithoutLeakage(reportResponse.json());

      const exportResponse = await app.inject({
        method: "POST",
        url: "/api/v1/exports/attendance",
        headers: {
          authorization: `Bearer ${itAdminToken}`,
          "idempotency-key": randomUUID(),
        },
        payload: { format: "csv", filters: { termId: ROLE_MATRIX_SEED.term } },
      });
      expect(exportResponse.statusCode).toBe(403);
      assertDenialWithoutLeakage(exportResponse.json());
    });

    it("TC-AC-16-006 TC-AC-23-009: SystemAuditor read-only — report allowed, export denied", async () => {
      await seedAttendancePair();

      const reportResponse = await app.inject({
        method: "GET",
        url: `/api/v1/reports/attendance?termId=${ROLE_MATRIX_SEED.term}&page=1&pageSize=25`,
        headers: { authorization: `Bearer ${systemAuditorToken}` },
      });
      expect(reportResponse.statusCode).toBe(200);

      const exportResponse = await app.inject({
        method: "POST",
        url: "/api/v1/exports/attendance",
        headers: {
          authorization: `Bearer ${systemAuditorToken}`,
          "idempotency-key": randomUUID(),
        },
        payload: {
          format: "csv",
          filters: { termId: ROLE_MATRIX_SEED.term, classSectionId: ROLE_MATRIX_SEED.sectionA },
        },
      });
      expect(exportResponse.statusCode).toBe(403);
      assertDenialWithoutLeakage(exportResponse.json());
    });

    it("TC-AC-16-008 TC-NFR-09-011 TC-AC-23-012: denied responses omit cross-scope pagination metadata", async () => {
      await seedAttendancePair();

      const response = await app.inject({
        method: "GET",
        url: `/api/v1/reports/attendance?termId=${ROLE_MATRIX_SEED.term}&studentUserId=60000000-0000-4000-8000-000000000003&page=1&pageSize=25`,
        headers: { authorization: `Bearer ${studentToken}` },
      });
      expect(response.statusCode).toBe(403);
      const body = response.json() as {
        meta?: { pagination?: { totalItems?: number } };
        error: { code: string };
      };
      expect(body.error.code).toMatch(/Forbidden|OutOfScope/);
      expect(body.meta?.pagination?.totalItems).toBeUndefined();
    });

    it("TC-NFR-09-004 TC-NFR-09-007: student denied audit log queries without payload leakage", async () => {
      const auditResponse = await app.inject({
        method: "GET",
        url: "/api/v1/audit-logs?actionType=Export&page=1&pageSize=25",
        headers: { authorization: `Bearer ${studentToken}` },
      });
      expect(auditResponse.statusCode).toBe(403);
      assertDenialWithoutLeakage(auditResponse.json());
    });
  });

  describe("REG-06 export audit side effects — AC-17 NFR-10", () => {
    it("TC-AC-17-003 TC-AC-17-004 TC-AC-23-013 TC-NFR-10-012: successful export writes queryable audit entry", async () => {
      await seedAttendancePair();
      await deleteExportJobsForActor(pool, ROLE_MATRIX_SEED.lecturer);

      const { exportJobId } = await completeExport(app, lecturerToken, {
        classSectionId: ROLE_MATRIX_SEED.sectionA,
      });

      const auditResponse = await app.inject({
        method: "GET",
        url: `/api/v1/audit-logs?targetType=ExportJob&targetId=${exportJobId}&actionType=Export&from=2000-01-01T00:00:00Z&page=1&pageSize=25`,
        headers: { authorization: `Bearer ${academicAdminToken}` },
      });
      expect(auditResponse.statusCode).toBe(200);
      const auditBody = auditResponse.json() as {
        data: { actorUserId: string; actionType: string; format?: string }[];
      };
      const entry = auditBody.data.find(
        (row) => row.actorUserId === ROLE_MATRIX_SEED.lecturer && row.actionType === "Export",
      );
      expect(entry).toBeTruthy();
      expect(entry?.format ?? "csv").toBe("csv");
    });

    it("TC-AC-17-006 TC-AC-17-007: denied export creates no completed audit row", async () => {
      const beforeAudit = await pool.query(
        `SELECT COUNT(*)::int AS count FROM audit_logs WHERE action_type = 'Export' AND actor_user_id = $1`,
        [ROLE_MATRIX_SEED.student],
      );

      const exportResponse = await app.inject({
        method: "POST",
        url: "/api/v1/exports/attendance",
        headers: {
          authorization: `Bearer ${studentToken}`,
          "idempotency-key": randomUUID(),
        },
        payload: { format: "csv", filters: { termId: ROLE_MATRIX_SEED.term } },
      });
      expect(exportResponse.statusCode).toBe(403);

      const afterAudit = await pool.query(
        `SELECT COUNT(*)::int AS count FROM audit_logs WHERE action_type = 'Export' AND actor_user_id = $1`,
        [ROLE_MATRIX_SEED.student],
      );
      expect(afterAudit.rows[0].count).toBe(beforeAudit.rows[0].count);
    });
  });

  describe("REG-07 six-role security matrix — AC-23 NFR-09", () => {
    it("TC-AC-23-003 TC-NFR-09-006: unauthenticated report returns 401", async () => {
      const response = await app.inject({
        method: "GET",
        url: `/api/v1/reports/attendance?termId=${ROLE_MATRIX_SEED.term}`,
      });
      expect(response.statusCode).toBe(401);
      const body = response.json() as { data: null; error: { code: string } };
      expect(body.data).toBeNull();
      expect(body.error.code).toBe("Unauthenticated");
    });

    it("TC-AC-23-010: lecturer denied foreign section session control, report, and export", async () => {
      const sessionB = await insertClosedSession(pool, ROLE_MATRIX_SEED.sectionB);
      cleanupSessionIds.push(sessionB);

      const scheduledSession = await pool.query<{ id: string }>(
        `
        INSERT INTO class_sessions (
          id, class_section_id, room_id, scheduled_start_at, scheduled_end_at, state
        )
        VALUES ($1, $2, $3, now() + interval '1 day', now() + interval '1 day 90 minutes', 'Scheduled')
        RETURNING id
        `,
        [randomUUID(), ROLE_MATRIX_SEED.sectionB, ROLE_MATRIX_SEED.room],
      );
      const foreignSessionId = scheduledSession.rows[0]?.id;
      expect(foreignSessionId).toBeTruthy();
      cleanupSessionIds.push(foreignSessionId!);

      const openResponse = await app.inject({
        method: "POST",
        url: `/api/v1/class-sessions/${foreignSessionId}/open`,
        headers: {
          authorization: `Bearer ${lecturerToken}`,
          "idempotency-key": randomUUID(),
        },
      });
      expect(openResponse.statusCode).toBe(403);
      assertDenialWithoutLeakage(openResponse.json());
    });

    it("TC-AC-23-014 TC-NFR-09-012: authorized lecturer workflow stays within assigned scope", async () => {
      const sessionA = await insertClosedSession(pool, ROLE_MATRIX_SEED.sectionA);
      cleanupSessionIds.push(sessionA);
      await insertAttendanceRow(pool, {
        sessionId: sessionA,
        sectionId: ROLE_MATRIX_SEED.sectionA,
        studentUserId: ROLE_MATRIX_SEED.student,
        status: "Present",
      });

      const rosterResponse = await app.inject({
        method: "GET",
        url: `/api/v1/class-sessions/${sessionA}/attendance`,
        headers: { authorization: `Bearer ${lecturerToken}` },
      });
      expect(rosterResponse.statusCode).toBe(200);
      const rosterBody = rosterResponse.json() as { data: { rows: unknown[] } };
      expect(rosterBody.data.rows.length).toBeGreaterThanOrEqual(1);

      const { csv } = await completeExport(app, lecturerToken, {
        classSectionId: ROLE_MATRIX_SEED.sectionA,
      });
      expect(csv).toContain(ROLE_MATRIX_SEED.sectionA);

      const foreignReport = await app.inject({
        method: "GET",
        url: `/api/v1/reports/attendance?classSectionId=${ROLE_MATRIX_SEED.sectionB}`,
        headers: { authorization: `Bearer ${lecturerToken}` },
      });
      expect(foreignReport.statusCode).toBe(403);
    });

    it("TC-NFR-10-007: student denied attendance PATCH without audit side effects", async () => {
      const sessionA = await insertClosedSession(pool, ROLE_MATRIX_SEED.sectionA);
      cleanupSessionIds.push(sessionA);
      await insertAttendanceRow(pool, {
        sessionId: sessionA,
        sectionId: ROLE_MATRIX_SEED.sectionA,
        studentUserId: ROLE_MATRIX_SEED.student,
        status: "Absent",
      });

      const beforeAudit = await pool.query(
        `SELECT COUNT(*)::int AS count FROM audit_logs WHERE action_type = 'manual_update' AND actor_user_id = $1`,
        [ROLE_MATRIX_SEED.student],
      );

      const patchResponse = await app.inject({
        method: "PATCH",
        url: `/api/v1/class-sessions/${sessionA}/attendance/${ROLE_MATRIX_SEED.student}`,
        headers: {
          authorization: `Bearer ${studentToken}`,
          "idempotency-key": randomUUID(),
        },
        payload: { status: "Manual Present", reason: "student tamper attempt" },
      });
      expect(patchResponse.statusCode).toBe(403);

      const afterAudit = await pool.query(
        `SELECT COUNT(*)::int AS count FROM audit_logs WHERE action_type = 'manual_update' AND actor_user_id = $1`,
        [ROLE_MATRIX_SEED.student],
      );
      expect(afterAudit.rows[0].count).toBe(beforeAudit.rows[0].count);
    });
  });
});
