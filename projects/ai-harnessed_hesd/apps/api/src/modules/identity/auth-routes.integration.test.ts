/**
 * Traceability: FR-15 FR-31 FR-32 FR-38 FR-37 BR-19 BR-24 BR-22 NFR-09 AC-15 AC-19 AC-26 FLOW-15 PRM-03
 * TC-FR-15-003 TC-FR-15-004 TC-FR-37-001 TC-FR-37-005 TC-FR-37-009 TC-BR-19-005 TC-BR-19-009 TC-NFR-09-004 TC-NFR-09-005 TC-NFR-09-006 TC-NFR-09-012
 * TC-FR-32-005 TC-FR-32-007 TC-FR-32-009
 * TC-FR-38-001 TC-FR-38-002 TC-FR-38-003 TC-FR-38-004 TC-FR-38-005 TC-FR-38-009 TC-BR-24-001 TC-BR-24-002 TC-BR-24-003 TC-BR-24-006 TC-BR-24-007
 */
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../../app.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const TEST_PASSWORD = "attendly-test-password";
const SEED = {
  faculty: "10000000-0000-4000-8000-000000000001",
  sessionOpen: "70000000-0000-4000-8000-000000000002",
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
      // schema may still be migrating in parallel integration suites
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
  const body = response.json() as { data: { accessToken: string; roles: string[] } };
  expect(body.data.accessToken).toBeTruthy();
  return body.data.accessToken;
}

async function logout(app: FastifyInstance, token: string) {
  return app.inject({
    method: "POST",
    url: "/api/v1/auth/logout",
    headers: { authorization: `Bearer ${token}` },
  });
}

describe("auth HTTP routes — FR-15 FR-31 FR-32 FR-38 BR-19 BR-24 NFR-09", () => {
  let app: FastifyInstance;
  let pool: pg.Pool;

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

    const extraRoles = [
      { email: "dept-admin@attendly.local", role: "DepartmentAdmin", scopeType: "Faculty", scopeId: SEED.faculty },
      { email: "it-admin@attendly.local", role: "ITAdmin", scopeType: "Institution", scopeId: null },
    ];
    for (const entry of extraRoles) {
      const existing = await pool.query<{ id: string }>(
        `SELECT id FROM users WHERE lower(email) = lower($1)`,
        [entry.email],
      );
      const userId = existing.rows[0]?.id ?? randomUUID();
      if (!existing.rows[0]) {
        await pool.query(
          `INSERT INTO users (id, email, display_name, is_active) VALUES ($1, $2, $3, true)`,
          [userId, entry.email, entry.role],
        );
      }
      await pool.query(
        `
        INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT DO NOTHING
        `,
        [randomUUID(), userId, entry.role, entry.scopeType, entry.scopeId],
      );
      await pool.query(
        `
        INSERT INTO user_credentials (user_id, password_hash)
        VALUES ($1, '$2b$10$1yMZjG/gIlHk/2kkZvMvt..ZRMavzIRAD9Rz9ipO7EHz87QF79Qpq')
        ON CONFLICT (user_id) DO NOTHING
        `,
        [userId],
      );
    }
  });

  afterAll(async () => {
    await app?.close();
    await pool?.end().catch(() => undefined);
  });

  it("TC-FR-15-003: student login then GET /me returns identity and scope", async () => {
    const token = await login(app, "student1@attendly.local");
    const me = await app.inject({
      method: "GET",
      url: "/api/v1/me",
      headers: { authorization: `Bearer ${token}` },
    });
    expect(me.statusCode).toBe(200);
    const body = me.json() as {
      data: { userId: string; roles: string[]; scopes: unknown[] };
      error: null;
    };
    expect(body.error).toBeNull();
    expect(body.data.userId).toBe("60000000-0000-4000-8000-000000000002");
    expect(body.data.roles).toContain("Student");
    expect(body.data.scopes.length).toBeGreaterThan(0);
  });

  it("TC-FR-15-004: unauthenticated POST /check-ins returns 401 Unauthenticated", async () => {
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      payload: { qrToken: "opaque", clientTimestamp: new Date().toISOString() },
    });
    expect(response.statusCode).toBe(401);
    const body = response.json() as { data: null; error: { code: string } };
    expect(body.data).toBeNull();
    expect(body.error.code).toBe("Unauthenticated");
  });

  it("TC-FR-15-006: non-student roles denied check-in with Forbidden", async () => {
    const lecturerToken = await login(app, "lecturer@attendly.local");
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: { authorization: `Bearer ${lecturerToken}` },
      payload: { qrToken: "opaque", clientTimestamp: new Date().toISOString() },
    });
    expect(response.statusCode).toBe(403);
    const body = response.json() as { error: { code: string } };
    expect(body.error.code).toBe("Forbidden");
  });

  it("TC-FR-37-005 TC-FR-37-001 PRM-03: student GET /reports/attendance returns self-scoped envelope", async () => {
    const token = await login(app, "student1@attendly.local");
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/reports/attendance?termId=20000000-0000-4000-8000-000000000001&page=1&pageSize=25",
      headers: { authorization: `Bearer ${token}` },
    });
    expect(response.statusCode).toBe(200);
    const body = response.json() as {
      data: unknown[] | null;
      error: null;
      meta: { pagination?: { page: number; pageSize: number; totalItems: number } };
    };
    expect(body.error).toBeNull();
    expect(Array.isArray(body.data)).toBe(true);
    expect(body.meta.pagination?.page).toBe(1);
  });

  it("TC-FR-37-009 PRM-03: student denied when querying another student via studentUserId override", async () => {
    const token = await login(app, "student1@attendly.local");
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/reports/attendance?termId=20000000-0000-4000-8000-000000000001&studentUserId=60000000-0000-4000-8000-000000000003&page=1&pageSize=25",
      headers: { authorization: `Bearer ${token}` },
    });
    expect(response.statusCode).toBe(403);
    const body = response.json() as { data: null; error: { code: string } };
    expect(body.data).toBeNull();
    expect(["Forbidden", "OutOfScope"]).toContain(body.error.code);
  });

  it("TC-BR-19-005: student denied POST /exports/attendance", async () => {
    const token = await login(app, "student1@attendly.local");
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/exports/attendance",
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        format: "csv",
        filters: { termId: "20000000-0000-4000-8000-000000000001" },
      },
    });
    expect(response.statusCode).toBe(403);
    const body = response.json() as { data: null; error: { code: string } };
    expect(body.data).toBeNull();
    expect(body.error.code).toBe("Forbidden");
  });

  it("TC-NFR-09-004: student denied GET /audit-logs", async () => {
    const token = await login(app, "student1@attendly.local");
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/audit-logs?page=1&pageSize=25",
      headers: { authorization: `Bearer ${token}` },
    });
    expect(response.statusCode).toBe(403);
    const body = response.json() as { data: null; error: { code: string } };
    expect(body.data).toBeNull();
    expect(["Forbidden", "OutOfScope"]).toContain(body.error.code);
  });

  it("TC-NFR-09-006: unauthenticated report request returns 401", async () => {
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/reports/attendance?termId=20000000-0000-4000-8000-000000000001",
    });
    expect(response.statusCode).toBe(401);
    const body = response.json() as { data: null; error: { code: string } };
    expect(body.error.code).toBe("Unauthenticated");
  });

  it("TC-NFR-09-005: lecturer denied export for unassigned classSectionId", async () => {
    const token = await login(app, "lecturer@attendly.local");
    const foreignSection = randomUUID();
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/exports/attendance",
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: { format: "csv", filters: { classSectionId: foreignSection } },
    });
    expect(response.statusCode).toBe(403);
    const body = response.json() as { data: null; error: { code: string } };
    expect(body.data).toBeNull();
    expect(body.error.code).toBe("OutOfScope");
  });

  it("academic admin login returns institution scope on GET /me (FR-31)", async () => {
    const token = await login(app, "academic-admin@attendly.local");
    const me = await app.inject({
      method: "GET",
      url: "/api/v1/me",
      headers: { authorization: `Bearer ${token}` },
    });
    const body = me.json() as { data: { roles: string[]; scopes: { role: string; scopeType: string }[] } };
    expect(body.data.roles).toContain("AcademicAdmin");
    expect(body.data.scopes.some((s) => s.role === "AcademicAdmin" && s.scopeType === "Institution")).toBe(
      true,
    );
  });

  it("TC-FR-38-003 TC-BR-24-001: POST /auth/logout then GET /me without token returns 401", async () => {
    const token = await login(app, "student1@attendly.local");
    const logoutRes = await logout(app, token);
    expect(logoutRes.statusCode).toBe(200);
    const logoutBody = logoutRes.json() as { data: { loggedOut: boolean }; error: null };
    expect(logoutBody.error).toBeNull();
    expect(logoutBody.data.loggedOut).toBe(true);

    const me = await app.inject({ method: "GET", url: "/api/v1/me" });
    expect(me.statusCode).toBe(401);
    const meBody = me.json() as { error: { code: string } };
    expect(meBody.error.code).toBe("Unauthenticated");
  });

  it("TC-FR-38-004 TC-BR-24-006: unauthenticated POST /auth/logout returns 401", async () => {
    const response = await app.inject({ method: "POST", url: "/api/v1/auth/logout" });
    expect(response.statusCode).toBe(401);
    const body = response.json() as { data: null; error: { code: string } };
    expect(body.data).toBeNull();
    expect(body.error.code).toBe("Unauthenticated");
  });

  it("TC-FR-38-001 TC-BR-24-003: voluntary logout across authenticated roles", async () => {
    const roleEmails = [
      "student1@attendly.local",
      "lecturer@attendly.local",
      "academic-admin@attendly.local",
      "dept-admin@attendly.local",
      "it-admin@attendly.local",
      "system-auditor@attendly.local",
    ];

    for (const email of roleEmails) {
      const token = await login(app, email);
      const meBefore = await app.inject({
        method: "GET",
        url: "/api/v1/me",
        headers: { authorization: `Bearer ${token}` },
      });
      expect(meBefore.statusCode).toBe(200);

      const logoutRes = await logout(app, token);
      expect(logoutRes.statusCode).toBe(200);
      expect((logoutRes.json() as { data: { loggedOut: boolean } }).data.loggedOut).toBe(true);

      const meAfter = await app.inject({ method: "GET", url: "/api/v1/me" });
      expect(meAfter.statusCode).toBe(401);
    }
  });

  it("TC-FR-38-002 TC-BR-24-002: logout emits UserLoggedOut audit without attendance mutations", async () => {
    const token = await login(app, "lecturer@attendly.local");
    const lecturerId = (
      await pool.query<{ id: string }>(
        `SELECT id FROM users WHERE email = 'lecturer@attendly.local'`,
      )
    ).rows[0].id;

    const logoutRes = await logout(app, token);
    expect(logoutRes.statusCode).toBe(200);
    const logoutBody = logoutRes.json() as {
      data: { loggedOut: boolean };
      meta: { requestId: string };
    };
    expect(logoutBody.data.loggedOut).toBe(true);

    const audit = await pool.query<{ action_type: string; actor_user_id: string; new_value: unknown }>(
      `
      SELECT action_type, actor_user_id, new_value
      FROM audit_logs
      WHERE actor_user_id = $1 AND action_type = 'UserLoggedOut'
      ORDER BY timestamp DESC
      LIMIT 1
      `,
      [lecturerId],
    );
    expect(audit.rowCount).toBeGreaterThan(0);
    expect(audit.rows[0].action_type).toBe("UserLoggedOut");
    expect(audit.rows[0].actor_user_id).toBe(lecturerId);
    const payload = audit.rows[0].new_value as { actorUserId?: string; occurredAt?: string };
    expect(payload.actorUserId).toBe(lecturerId);
    expect(payload.occurredAt).toBeTruthy();

    const sideEffects = await pool.query<{ action_type: string }>(
      `
      SELECT action_type
      FROM audit_logs
      WHERE correlation_id = $1 AND action_type <> 'UserLoggedOut'
      `,
      [logoutBody.meta.requestId],
    );
    expect(sideEffects.rowCount ?? 0).toBe(0);

    const me = await app.inject({ method: "GET", url: "/api/v1/me" });
    expect(me.statusCode).toBe(401);
  });

  it("TC-FR-38-009 TC-BR-24-007: post-logout role-scoped APIs return 401 until re-login", async () => {
    const studentToken = await login(app, "student1@attendly.local");
    await logout(app, studentToken);

    const checkInDenied = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: { "idempotency-key": randomUUID() },
      payload: { qrToken: "opaque", clientTimestamp: new Date().toISOString() },
    });
    expect(checkInDenied.statusCode).toBe(401);

    const reportDenied = await app.inject({
      method: "GET",
      url: "/api/v1/reports/attendance?termId=20000000-0000-4000-8000-000000000001",
    });
    expect(reportDenied.statusCode).toBe(401);

    const lecturerToken = await login(app, "lecturer@attendly.local");
    await logout(app, lecturerToken);

    const rosterDenied = await app.inject({
      method: "GET",
      url: `/api/v1/class-sessions/${SEED.sessionOpen}/attendance`,
    });
    expect(rosterDenied.statusCode).toBe(401);

    const studentTokenAgain = await login(app, "student1@attendly.local");
    const reportOk = await app.inject({
      method: "GET",
      url: "/api/v1/reports/attendance?termId=20000000-0000-4000-8000-000000000001&page=1&pageSize=25",
      headers: { authorization: `Bearer ${studentTokenAgain}` },
    });
    expect(reportOk.statusCode).toBe(200);
  });
});
