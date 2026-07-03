/**
 * Traceability: FR-29 FR-30 BR-22 BR-23 AC-18 AC-19 NFR-13
 * TC-AC-19-006 TC-AC-19-011 TC-FR-29-006 TC-FR-29-014 TC-FR-30-005 TC-NFR-13-002 TC-NFR-13-006 TC-NFR-13-010
 */
import { createHash, randomUUID } from "node:crypto";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../../app.js";
import { QR_TTL_MS } from "../check-in-and-qr-orchestrator/qr-service.js";
import { createReportingRepository } from "../reporting-and-export/repository.js";
import { resolveReportExportScope } from "../reporting-and-export/scope.js";
import type { ActorContext } from "../identity/types.js";
import { createIdentityRepository } from "../identity/repository.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const TEST_PASSWORD = "attendly-test-password";

const SEED = {
  term: "20000000-0000-4000-8000-000000000001",
  section: "50000000-0000-4000-8000-000000000001",
  room: "40000000-0000-4000-8000-000000000001",
  lecturer: "60000000-0000-4000-8000-000000000001",
  student: "60000000-0000-4000-8000-000000000002",
  academicAdmin: "60000000-0000-4000-8000-000000000005",
};

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

async function insertClosedSession(pool: pg.Pool, closedAt = new Date()): Promise<string> {
  const sessionId = randomUUID();
  const start = new Date(closedAt.getTime() - 90 * 60_000);
  const end = new Date(closedAt.getTime() - 30 * 60_000);
  await pool.query(
    `
    INSERT INTO class_sessions (
      id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
      state, opened_at, opened_by_user_id, closed_at, closed_by_user_id
    )
    VALUES ($1, $2, $3, $4, $5, 'Closed', $6, $7, $8, $7)
    `,
    [sessionId, SEED.section, SEED.room, start, end, start, SEED.lecturer, closedAt],
  );
  return sessionId;
}

describe("M08 audit and compliance — FR-29 FR-30 BR-22 BR-23 AC-18 AC-19 NFR-13", () => {
  let app: FastifyInstance;
  let pool: pg.Pool;
  const sessionIds: string[] = [];
  const exportJobIds: string[] = [];
  const ephemeralExportActorIds: string[] = [];

  beforeAll(async () => {
    expect(databaseUrl).toBeTruthy();
    process.env.DATABASE_URL = databaseUrl;
    process.env.JWT_SECRET = "test-jwt";
    const probe = new pg.Client({ connectionString: databaseUrl });
    await probe.connect();
    await waitForSeededDb(probe);
    await probe.end();
    pool = new pg.Pool({ connectionString: databaseUrl });
    app = await buildApp();
    await app.ready();
  });

  afterEach(async () => {
    const exportIds = exportJobIds.splice(0);
    if (exportIds.length > 0) {
      await pool.query(
        `DELETE FROM audit_logs WHERE target_type = 'ExportJob' AND target_id = ANY($1::uuid[])`,
        [exportIds],
      );
      await pool.query(`DELETE FROM export_jobs WHERE id = ANY($1::uuid[])`, [exportIds]);
    }
    const actorIds = ephemeralExportActorIds.splice(0);
    if (actorIds.length > 0) {
      await pool.query(`DELETE FROM users WHERE id = ANY($1::uuid[])`, [actorIds]);
    }
    for (const sessionId of sessionIds.splice(0)) {
      await pool.query(`DELETE FROM audit_logs WHERE correlation_id IN (
        SELECT correlation_id FROM check_in_attempts WHERE class_session_id = $1
      )`, [sessionId]);
      await pool.query(`DELETE FROM check_in_attempts WHERE class_session_id = $1`, [sessionId]);
      await pool.query(`DELETE FROM audit_logs WHERE target_id IN (
        SELECT id FROM attendance_records WHERE class_session_id = $1
      )`, [sessionId]);
      await pool.query(`DELETE FROM attendance_records WHERE class_session_id = $1`, [sessionId]);
      await pool.query(`DELETE FROM qr_session_tokens WHERE class_session_id = $1`, [sessionId]);
      await pool.query(`DELETE FROM audit_logs WHERE target_id = $1`, [sessionId]);
      await pool.query(`DELETE FROM class_sessions WHERE id = $1`, [sessionId]);
    }
  });

  afterAll(async () => {
    await app?.close();
    await pool?.end().catch(() => undefined);
  });

  it("TC-AC-19-006 TC-FR-29-006: manual correction is queryable via GET /audit-logs", async () => {
    const resolvedSessionId = await insertClosedSession(pool);
    sessionIds.push(resolvedSessionId);
    const recordId = randomUUID();
    await pool.query(
      `
      INSERT INTO attendance_records (
        id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
      )
      VALUES ($1, $2, $3, $4, 'Absent', $5)
      `,
      [recordId, resolvedSessionId, SEED.section, SEED.student, SEED.lecturer],
    );

    const lecturerToken = await login(app, "lecturer@attendly.local");
    const adminToken = await login(app, "academic-admin@attendly.local");
    const mutationStart = new Date(Date.now() - 60_000).toISOString();

    const patch = await app.inject({
      method: "PATCH",
      url: `/api/v1/class-sessions/${resolvedSessionId}/attendance/${SEED.student}`,
      headers: {
        authorization: `Bearer ${lecturerToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        status: "Manual Present",
        reason: "Sinh vien co mat nhung loi camera tren thiet bi.",
      },
    });
    expect(patch.statusCode).toBe(200);

    const auditResponse = await app.inject({
      method: "GET",
      url: `/api/v1/audit-logs?targetType=AttendanceRecord&targetId=${SEED.student}&actionType=manual_update&from=${mutationStart}&page=1&pageSize=25`,
      headers: { authorization: `Bearer ${adminToken}` },
    });
    expect(auditResponse.statusCode).toBe(200);

    const body = auditResponse.json() as {
      data: Array<{
        actorUserId: string;
        oldStatus: string;
        newStatus: string;
        reason: string;
        actionType: string;
        correlationId: string;
      }>;
      error: null;
      meta: { pagination: { totalItems: number } };
    };
    expect(body.error).toBeNull();
    expect(body.meta.pagination.totalItems).toBeGreaterThanOrEqual(1);
    const entry = body.data.find((row) => row.newStatus === "Manual Present");
    expect(entry).toBeTruthy();
    expect(entry?.actionType).toBe("manual_update");
    expect(entry?.oldStatus).toBe("Absent");
    expect(entry?.actorUserId).toBe(SEED.lecturer);
    expect(entry?.reason).toContain("camera");
    expect(entry?.correlationId).toBeTruthy();
  });

  it("TC-FR-29-014 TC-AC-19-011: rejected correction outside edit window writes no mutation audit", async () => {
    const closedAt = new Date(Date.now() - 48 * 60 * 60 * 1000);
    const sessionId = await insertClosedSession(pool, closedAt);
    sessionIds.push(sessionId);
    const recordId = randomUUID();
    await pool.query(
      `
      INSERT INTO attendance_records (
        id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
      )
      VALUES ($1, $2, $3, $4, 'Absent', $5)
      `,
      [recordId, sessionId, SEED.section, SEED.student, SEED.lecturer],
    );

    const beforeCount = await pool.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM audit_logs WHERE target_id = $1 AND action_type = 'AttendanceUpdate'`,
      [recordId],
    );
    const baseline = Number.parseInt(beforeCount.rows[0]?.count ?? "0", 10);

    const lecturerToken = await login(app, "lecturer@attendly.local");
    const denied = await app.inject({
      method: "PATCH",
      url: `/api/v1/class-sessions/${sessionId}/attendance/${SEED.student}`,
      headers: {
        authorization: `Bearer ${lecturerToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: { status: "Manual Present", reason: "Should be rejected." },
    });
    expect(denied.statusCode).toBe(409);

    const afterCount = await pool.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM audit_logs WHERE target_id = $1 AND action_type = 'AttendanceUpdate'`,
      [recordId],
    );
    expect(Number.parseInt(afterCount.rows[0]?.count ?? "0", 10)).toBe(baseline);
  });

  it("TC-NFR-13-006: failed ExpiredQr check-in is queryable via GET /audit-logs", async () => {
    const sessionId = randomUUID();
    sessionIds.push(sessionId);
    const start = new Date();
    const end = new Date(start.getTime() + 90 * 60_000);
    await pool.query(
      `
      INSERT INTO class_sessions (
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
        state, opened_at, opened_by_user_id
      )
      VALUES ($1, $2, $3, $4, $5, 'Open', $6, $7)
      `,
      [sessionId, SEED.section, SEED.room, start, end, start, SEED.lecturer],
    );

    const qrPayload = randomUUID();
    const expiredAt = new Date(Date.now() - 60_000);
    const issuedAt = new Date(expiredAt.getTime() - QR_TTL_MS);
    const tokenHash = createHash("sha256").update(qrPayload).digest("hex");
    await pool.query(
      `
      INSERT INTO qr_session_tokens (id, class_session_id, token_hash, state, issued_at, expires_at)
      VALUES ($1, $2, $3, 'Valid', $4, $5)
      `,
      [randomUUID(), sessionId, tokenHash, issuedAt.toISOString(), expiredAt.toISOString()],
    );

    const studentToken = await login(app, "student1@attendly.local");
    const adminToken = await login(app, "academic-admin@attendly.local");
    const requestId = randomUUID();
    const attemptStart = new Date(Date.now() - 60_000).toISOString();

    const checkIn = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: {
        authorization: `Bearer ${studentToken}`,
        "idempotency-key": randomUUID(),
        "x-request-id": requestId,
      },
      payload: {
        qrToken: qrPayload,
        clientTimestamp: new Date().toISOString(),
      },
    });
    expect(checkIn.statusCode).toBe(422);

    const auditResponse = await app.inject({
      method: "GET",
      url: `/api/v1/audit-logs?actionType=CheckInAttemptRecorded&targetId=${SEED.student}&classSessionId=${sessionId}&from=${attemptStart}&page=1&pageSize=25`,
      headers: { authorization: `Bearer ${adminToken}` },
    });
    expect(auditResponse.statusCode).toBe(200);

    const body = auditResponse.json() as {
      data: Array<{ outcome: string; studentUserId: string; classSessionId: string }>;
    };
    const entry = body.data.find((row) => row.outcome === "ExpiredQr");
    expect(entry).toBeTruthy();
    expect(entry?.studentUserId).toBe(SEED.student);
    expect(entry?.classSessionId).toBe(sessionId);
  });

  it("TC-FR-30-005 TC-NFR-13-007: completed export is queryable via GET /audit-logs", async () => {
    const adminToken = await login(app, "academic-admin@attendly.local");

    const identityRepo = createIdentityRepository(pool);
    const reportingRepo = createReportingRepository(pool);
    const ephemeralUserId = randomUUID();
    await pool.query(
      `INSERT INTO users (id, email, display_name, is_active) VALUES ($1, $2, $3, true)`,
      [ephemeralUserId, `audit-export-${ephemeralUserId}@test.local`, "Audit Export Actor"],
    );
    ephemeralExportActorIds.push(ephemeralUserId);

    const ephemeralActor: ActorContext = {
      userId: ephemeralUserId,
      email: `audit-export-${ephemeralUserId}@test.local`,
      displayName: "Audit Export Actor",
      roles: ["Lecturer"],
      assignments: [{ role: "Lecturer", scopeType: "ClassSection", scopeId: SEED.section }],
    };

    const scopeAccess = await resolveReportExportScope(
      ephemeralActor,
      identityRepo,
      { termId: SEED.term, classSectionId: SEED.section },
      "ExportJob",
    );
    expect(scopeAccess.allowed).toBe(true);
    if (!scopeAccess.allowed) return;

    const correlationId = randomUUID();
    const job = await reportingRepo.createExportJob({
      actor: ephemeralActor,
      format: "csv",
      filters: { termId: SEED.term, classSectionId: SEED.section },
      scope: scopeAccess.scope,
      correlationId,
    });
    expect(job.status).toBe("Completed");
    exportJobIds.push(job.exportJobId);

    const auditResponse = await app.inject({
      method: "GET",
      url: `/api/v1/audit-logs?targetType=ExportJob&targetId=${job.exportJobId}&actionType=Export&from=2000-01-01T00:00:00Z&page=1&pageSize=25`,
      headers: { authorization: `Bearer ${adminToken}` },
    });
    expect(auditResponse.statusCode).toBe(200);

    const body = auditResponse.json() as {
      data: Array<{
        id: string;
        targetId: string;
        actionType: string;
        actorUserId: string;
        format: string;
        scopeFilterSummary: string | null;
      }>;
      meta: { pagination: { totalItems: number } };
    };
    expect(body.meta.pagination.totalItems).toBeGreaterThanOrEqual(1);
    const entry =
      body.data.find((row) => row.targetId === job.exportJobId) ??
      body.data.find((row) => row.actionType === "Export" && row.actorUserId === ephemeralUserId);
    expect(entry).toBeTruthy();
    expect(entry?.actorUserId).toBe(ephemeralUserId);
    expect(entry?.format).toBe("csv");
    expect(entry?.scopeFilterSummary).toContain(SEED.section);
  });

  it("TC-NFR-13-010: student denied GET /audit-logs without leakage", async () => {
    const studentToken = await login(app, "student1@attendly.local");
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/audit-logs?page=1&pageSize=25",
      headers: { authorization: `Bearer ${studentToken}` },
    });
    expect(response.statusCode).toBe(403);
    const body = response.json() as { data: null; error: { code: string } };
    expect(body.data).toBeNull();
    expect(["Forbidden", "OutOfScope"]).toContain(body.error.code);
  });
});
