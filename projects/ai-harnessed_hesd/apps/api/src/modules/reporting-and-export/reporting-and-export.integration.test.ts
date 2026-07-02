/**
 * Traceability: FR-27 FR-28 BR-18 BR-19 AC-15 AC-16 AC-17
 * TC-FR-27-002 TC-FR-27-003 TC-FR-28-002 TC-FR-28-003 TC-FR-28-010 TC-AC-15-002 TC-AC-16-002 TC-AC-17-002 TC-BR-18-002 TC-BR-18-003 TC-BR-19-002 TC-BR-19-003
 */
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../../app.js";
import { createIdentityRepository } from "../identity/repository.js";
import { createReportingRepository } from "./repository.js";
import { resolveReportExportScope } from "./scope.js";

const execFileAsync = promisify(execFile);
const REPO_ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../../../../..");

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const TEST_PASSWORD = "attendly-test-password";

const SEED = {
  faculty: "10000000-0000-4000-8000-000000000001",
  term: "20000000-0000-4000-8000-000000000001",
  course: "30000000-0000-4000-8000-000000000001",
  room: "40000000-0000-4000-8000-000000000001",
  sectionA: "50000000-0000-4000-8000-000000000001",
  lecturer: "60000000-0000-4000-8000-000000000001",
  student: "60000000-0000-4000-8000-000000000002",
  academicAdmin: "60000000-0000-4000-8000-000000000005",
};

async function ensureMigratedAndSeeded(): Promise<void> {
  await execFileAsync("node", ["scripts/db-migrate.mjs"], {
    cwd: REPO_ROOT,
    env: { ...process.env, DATABASE_URL: databaseUrl!, SEED_ENABLED: "true" },
  });
  await execFileAsync("node", ["scripts/db-seed.mjs"], {
    cwd: REPO_ROOT,
    env: { ...process.env, DATABASE_URL: databaseUrl!, SEED_ENABLED: "true" },
  });
}

async function waitForSeededDb(client: pg.Client, attempts = 60): Promise<void> {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const users = await client.query(`SELECT 1 FROM users LIMIT 1`);
      const creds = await client.query(`SELECT 1 FROM user_credentials LIMIT 1`);
      if ((users.rowCount ?? 0) > 0 && (creds.rowCount ?? 0) > 0) {
        return;
      }
    } catch {
      // schema may still be migrating
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Timed out waiting for migrated and seeded test database");
}

async function login(app: FastifyInstance, email: string): Promise<string> {
  const response = await app.inject({
    method: "POST",
    url: "/api/v1/auth/login",
    payload: { email, password: TEST_PASSWORD },
  });
  expect(response.statusCode).toBe(200);
  return (response.json() as { data: { accessToken: string } }).data.accessToken;
}

async function insertAttendanceRow(
  pool: pg.Pool,
  params: {
    sessionId: string;
    sectionId: string;
    studentUserId: string;
    status: string;
    checkInMethod?: string;
  },
): Promise<string> {
  const recordId = randomUUID();
  await pool.query(
    `
    INSERT INTO attendance_records (
      id, class_session_id, class_section_id, student_user_id, status, check_in_method, check_in_at
    )
    VALUES ($1, $2, $3, $4, $5, $6, now())
  `,
    [
      recordId,
      params.sessionId,
      params.sectionId,
      params.studentUserId,
      params.status,
      params.checkInMethod ?? "QR",
    ],
  );
  return recordId;
}

async function insertSectionB(pool: pg.Pool): Promise<string> {
  const sectionBId = randomUUID();
  await pool.query(
    `
    INSERT INTO class_sections (
      id, section_code, term_id, course_id, lecturer_user_id, default_room_id, capacity, is_active
    )
    VALUES ($1, 'SE101-02', $2, $3, $4, $5, 60, true)
    `,
    [sectionBId, SEED.term, SEED.course, SEED.lecturer, SEED.room],
  );
  return sectionBId;
}

async function insertClosedSession(
  pool: pg.Pool,
  sectionId: string,
  startAt = "2026-02-01T08:00:00Z",
): Promise<string> {
  const sessionId = randomUUID();
  const start = new Date(startAt);
  const end = new Date(start.getTime() + 90 * 60 * 1000);
  await pool.query(
    `
    INSERT INTO class_sessions (
      id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
      state, opened_at, opened_by_user_id, closed_at, closed_by_user_id
    )
    VALUES ($1, $2, $3, $4, $5, 'Closed', $4, $6, $5, $6)
    `,
    [sessionId, sectionId, SEED.room, start, end, SEED.lecturer],
  );
  return sessionId;
}

describe("M07 reporting and export — FR-27 FR-28 BR-18 BR-19 AC-15 AC-16 AC-17", () => {
  let app: FastifyInstance;
  let pool: pg.Pool;
  let reportingRepo: ReturnType<typeof createReportingRepository>;
  let identityRepo: ReturnType<typeof createIdentityRepository>;
  const cleanupSessionIds: string[] = [];
  const cleanupSectionIds: string[] = [];

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
    reportingRepo = createReportingRepository(pool);
    identityRepo = createIdentityRepository(pool);
  }, 60_000);

  afterEach(async () => {
    for (const sessionId of cleanupSessionIds.splice(0)) {
      await pool.query(`DELETE FROM attendance_records WHERE class_session_id = $1`, [sessionId]);
      await pool.query(`DELETE FROM class_sessions WHERE id = $1`, [sessionId]);
    }
    for (const sectionId of cleanupSectionIds.splice(0)) {
      await pool.query(`DELETE FROM attendance_records WHERE class_section_id = $1`, [sectionId]);
      await pool.query(`DELETE FROM class_sessions WHERE class_section_id = $1`, [sectionId]);
      await pool.query(`DELETE FROM class_sections WHERE id = $1`, [sectionId]);
    }
    await reportingRepo.deleteExportJobsForActor(SEED.lecturer);
    await reportingRepo.deleteExportJobsForActor(SEED.academicAdmin);
  });

  afterAll(async () => {
    await app?.close();
    await pool?.end().catch(() => undefined);
  });

  it("TC-FR-28-004 TC-AC-15-004: lecturer GET /reports/attendance returns scoped paginated rows", async () => {
    const sessionId = await insertClosedSession(pool, SEED.sectionA);
    cleanupSessionIds.push(sessionId);
    await insertAttendanceRow(pool, {
      sessionId,
      sectionId: SEED.sectionA,
      studentUserId: SEED.student,
      status: "Present",
    });

    const token = await login(app, "lecturer@attendly.local");
    const response = await app.inject({
      method: "GET",
      url: `/api/v1/reports/attendance?termId=${SEED.term}&classSectionId=${SEED.sectionA}&page=1&pageSize=25`,
      headers: { authorization: `Bearer ${token}` },
    });

    expect(response.statusCode).toBe(200);
    const body = response.json() as {
      data: { classSectionId: string }[];
      meta: { pagination: { totalItems: number } };
      error: null;
    };
    expect(body.error).toBeNull();
    expect(body.meta.pagination.totalItems).toBeGreaterThanOrEqual(1);
    expect(body.data.every((row) => row.classSectionId === SEED.sectionA)).toBe(true);
  });

  it("TC-FR-27-004 TC-AC-15-003: lecturer POST /exports/attendance returns 202 export job envelope", async () => {
    const sessionId = await insertClosedSession(pool, SEED.sectionA);
    cleanupSessionIds.push(sessionId);
    await insertAttendanceRow(pool, {
      sessionId,
      sectionId: SEED.sectionA,
      studentUserId: SEED.student,
      status: "Late",
      checkInMethod: "QR",
    });

    const token = await login(app, "lecturer@attendly.local");
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/exports/attendance",
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        format: "csv",
        filters: { termId: SEED.term, classSectionId: SEED.sectionA },
      },
    });

    expect(response.statusCode).toBe(202);
    const body = response.json() as {
      data: { exportJobId: string; status: string; format: string };
      meta: { requestId: string; timestamp: string };
      error: null;
    };
    expect(body.error).toBeNull();
    expect(body.data.exportJobId).toBeTruthy();
    expect(body.data.format).toBe("csv");
    expect(body.meta.requestId).toBeTruthy();
    expect(body.meta.timestamp).toBeTruthy();
  });

  it("TC-FR-27-015 TC-AC-17-003: lecturer downloads completed CSV artifact for own export", async () => {
    const sessionId = await insertClosedSession(pool, SEED.sectionA);
    cleanupSessionIds.push(sessionId);
    await insertAttendanceRow(pool, {
      sessionId,
      sectionId: SEED.sectionA,
      studentUserId: SEED.student,
      status: "Present",
    });

    const token = await login(app, "lecturer@attendly.local");
    const exportResponse = await app.inject({
      method: "POST",
      url: "/api/v1/exports/attendance",
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        format: "csv",
        filters: { termId: SEED.term, classSectionId: SEED.sectionA },
      },
    });
    const exportBody = exportResponse.json() as { data: { exportJobId: string } };

    const downloadResponse = await app.inject({
      method: "GET",
      url: `/api/v1/exports/attendance/${exportBody.data.exportJobId}`,
      headers: { authorization: `Bearer ${token}`, accept: "text/csv" },
    });

    expect(downloadResponse.statusCode).toBe(200);
    expect(downloadResponse.headers["content-type"]).toContain("text/csv");
    expect(downloadResponse.headers["content-disposition"]).toContain("attendance-export");
    expect(downloadResponse.body).toContain("studentCode");
    expect(downloadResponse.body).toContain(SEED.sectionA);
  });

  it("TC-FR-27-002 TC-AC-15-002 TC-BR-18-002: export scoped to lecturer assigned sections only", async () => {
    const sectionB = await insertSectionB(pool);
    cleanupSectionIds.push(sectionB);

    const sessionA = await insertClosedSession(pool, SEED.sectionA);
    const sessionB = await insertClosedSession(pool, sectionB);
    cleanupSessionIds.push(sessionA, sessionB);

    await insertAttendanceRow(pool, {
      sessionId: sessionA,
      sectionId: SEED.sectionA,
      studentUserId: SEED.student,
      status: "Present",
    });
    await insertAttendanceRow(pool, {
      sessionId: sessionB,
      sectionId: sectionB,
      studentUserId: SEED.student,
      status: "Absent",
    });

    const actor = await identityRepo.buildActorContext(SEED.lecturer);
    expect(actor).toBeTruthy();
    const access = await resolveReportExportScope(
      actor!,
      identityRepo,
      { termId: SEED.term },
      "ExportJob",
    );
    expect(access.allowed).toBe(true);

    const job = await reportingRepo.createExportJob({
      actor: actor!,
      format: "csv",
      filters: { termId: SEED.term },
      scope: access.scope,
      idempotencyKey: randomUUID(),
    });

    const artifact = await reportingRepo.getExportArtifact(job.exportJobId);
    expect(artifact).toBeTruthy();
    expect(artifact!.csv).toContain("studentCode");
    expect(artifact!.csv).toContain(SEED.sectionA);
    expect(artifact!.csv).not.toContain(sectionB);
  });

  it("TC-FR-27-003: CSV export includes required attendance columns", async () => {
    const sessionId = await insertClosedSession(pool, SEED.sectionA);
    cleanupSessionIds.push(sessionId);
    await insertAttendanceRow(pool, {
      sessionId,
      sectionId: SEED.sectionA,
      studentUserId: SEED.student,
      status: "Manual Present",
      checkInMethod: "Manual",
    });

    const actor = await identityRepo.buildActorContext(SEED.lecturer);
    const access = await resolveReportExportScope(
      actor!,
      identityRepo,
      { classSectionId: SEED.sectionA },
      "ExportJob",
    );
    const job = await reportingRepo.createExportJob({
      actor: actor!,
      format: "csv",
      filters: { classSectionId: SEED.sectionA },
      scope: access.scope,
    });

    const artifact = await reportingRepo.getExportArtifact(job.exportJobId);
    const header = artifact!.csv.split("\n")[0];
    expect(header).toContain("studentCode");
    expect(header).toContain("attendanceStatus");
    expect(header).toContain("checkInAt");
    expect(header).toContain("checkInMethod");
    expect(header).toContain("classSessionId");
    expect(artifact!.csv).toContain("Manual Present");
  });

  it("TC-FR-28-002 TC-BR-19-002: report query rejects out-of-scope classSectionId at module boundary", async () => {
    const sectionB = await insertSectionB(pool);
    cleanupSectionIds.push(sectionB);
    const sessionB = await insertClosedSession(pool, sectionB);
    cleanupSessionIds.push(sessionB);
    await insertAttendanceRow(pool, {
      sessionId: sessionB,
      sectionId: sectionB,
      studentUserId: SEED.student,
      status: "Present",
    });

    const actor = await identityRepo.buildActorContext(SEED.lecturer);
    const access = await resolveReportExportScope(
      actor!,
      identityRepo,
      { classSectionId: sectionB },
      "ReportView",
    );
    expect(access.allowed).toBe(false);
    if (!access.allowed) {
      expect(access.code).toBe("OutOfScope");
    }
  });

  it("TC-BR-19-003: student export denied before export_jobs persistence", async () => {
    const before = await pool.query(`SELECT COUNT(*)::int AS count FROM export_jobs`);
    const actor = await identityRepo.buildActorContext(SEED.student);
    const access = await resolveReportExportScope(
      actor!,
      identityRepo,
      { termId: SEED.term },
      "ExportJob",
    );
    expect(access.allowed).toBe(false);
    const after = await pool.query(`SELECT COUNT(*)::int AS count FROM export_jobs`);
    expect(after.rows[0].count).toBe(before.rows[0].count);
  });

  it("TC-FR-28-010 TC-AC-15-007: pagination metadata reflects scoped totals only", async () => {
    const sectionB = await insertSectionB(pool);
    cleanupSectionIds.push(sectionB);
    const scopedWindow = {
      termId: SEED.term,
      from: "2026-04-10T00:00:00.000Z",
      to: "2026-04-10T23:59:59.999Z",
    };
    const actor = await identityRepo.buildActorContext(SEED.lecturer);
    const access = await resolveReportExportScope(actor!, identityRepo, scopedWindow, "ReportView");
    const baseline = await reportingRepo.queryAttendanceReport({
      scope: access.scope,
      filters: scopedWindow,
      sortBy: "date",
      sortOrder: "desc",
      page: 1,
      pageSize: 25,
    });

    for (let i = 0; i < 3; i += 1) {
      const sessionId = await insertClosedSession(pool, SEED.sectionA, `2026-04-10T0${i}:00:00Z`);
      cleanupSessionIds.push(sessionId);
      await insertAttendanceRow(pool, {
        sessionId,
        sectionId: SEED.sectionA,
        studentUserId: SEED.student,
        status: "Present",
      });
    }

    for (let i = 0; i < 10; i += 1) {
      const sessionId = await insertClosedSession(pool, sectionB, `2026-04-10T1${i}:00:00Z`);
      cleanupSessionIds.push(sessionId);
      await insertAttendanceRow(pool, {
        sessionId,
        sectionId: sectionB,
        studentUserId: SEED.student,
        status: "Absent",
      });
    }

    const page1 = await reportingRepo.queryAttendanceReport({
      scope: access.scope,
      filters: scopedWindow,
      sortBy: "date",
      sortOrder: "desc",
      page: 1,
      pageSize: 25,
    });

    expect(page1.totalItems).toBe(baseline.totalItems + 3);
    expect(page1.rows.every((r) => r.classSectionId === SEED.sectionA)).toBe(true);
  });

  it("TC-AC-17-002 TC-BR-18-003: successful export writes audit log with actor and scope", async () => {
    const sessionId = await insertClosedSession(pool, SEED.sectionA);
    cleanupSessionIds.push(sessionId);
    await insertAttendanceRow(pool, {
      sessionId,
      sectionId: SEED.sectionA,
      studentUserId: SEED.student,
      status: "Present",
    });

    const actor = await identityRepo.buildActorContext(SEED.lecturer);
    const access = await resolveReportExportScope(
      actor!,
      identityRepo,
      { classSectionId: SEED.sectionA },
      "ExportJob",
    );
    const job = await reportingRepo.createExportJob({
      actor: actor!,
      format: "csv",
      filters: { classSectionId: SEED.sectionA },
      scope: access.scope,
    });

    const audit = await pool.query<{ action_type: string; actor_user_id: string; new_value: unknown }>(
      `
      SELECT action_type, actor_user_id, new_value
      FROM audit_logs
      WHERE target_type = 'ExportJob' AND target_id = $1
      `,
      [job.exportJobId],
    );

    expect(audit.rowCount).toBe(1);
    expect(audit.rows[0].action_type).toBe("Export");
    expect(audit.rows[0].actor_user_id).toBe(SEED.lecturer);
    const payload = audit.rows[0].new_value as { format: string };
    expect(payload.format).toBe("csv");
  });

  it("TC-FR-27-014 TC-BR-18-014: duplicate Idempotency-Key returns same export job", async () => {
    const sessionId = await insertClosedSession(pool, SEED.sectionA);
    cleanupSessionIds.push(sessionId);
    await insertAttendanceRow(pool, {
      sessionId,
      sectionId: SEED.sectionA,
      studentUserId: SEED.student,
      status: "Present",
    });

    const token = await login(app, "lecturer@attendly.local");
    const key = randomUUID();
    const headers = { authorization: `Bearer ${token}`, "idempotency-key": key };
    const payload = {
      format: "csv",
      filters: { termId: SEED.term, classSectionId: SEED.sectionA },
    };

    const first = await app.inject({
      method: "POST",
      url: "/api/v1/exports/attendance",
      headers,
      payload,
    });
    const second = await app.inject({
      method: "POST",
      url: "/api/v1/exports/attendance",
      headers,
      payload,
    });

    const firstBody = first.json() as { data: { exportJobId: string } };
    const secondBody = second.json() as { data: { exportJobId: string } };
    expect(firstBody.data.exportJobId).toBe(secondBody.data.exportJobId);

    const count = await pool.query(
      `SELECT COUNT(*)::int AS count FROM export_jobs WHERE idempotency_key = $1`,
      [key],
    );
    expect(count.rows[0].count).toBe(1);
  });

  it("TC-AC-16-006 TC-BR-19-005: student denied POST /exports/attendance via HTTP", async () => {
    const token = await login(app, "student1@attendly.local");
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/exports/attendance",
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: { format: "csv", filters: { termId: SEED.term } },
    });
    expect(response.statusCode).toBe(403);
    const body = response.json() as { data: null; error: { code: string } };
    expect(body.data).toBeNull();
    expect(body.error.code).toBe("Forbidden");
  });
});
