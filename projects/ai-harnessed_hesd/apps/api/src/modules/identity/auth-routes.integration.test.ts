/**
 * Traceability: FR-15 FR-31 FR-32 BR-19 BR-22 NFR-09 AC-15 AC-19
 * TC-FR-15-003 TC-FR-15-004 TC-BR-19-004 TC-BR-19-005 TC-BR-19-009 TC-NFR-09-004 TC-NFR-09-005 TC-NFR-09-006 TC-NFR-09-012
 * TC-FR-32-005 TC-FR-32-007 TC-FR-32-009
 */
import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../../app.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const TEST_PASSWORD = "attendly-test-password";

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

describe("auth HTTP routes — FR-15 FR-31 FR-32 BR-19 NFR-09", () => {
  let app: FastifyInstance;

  beforeAll(async () => {
    expect(databaseUrl).toBeTruthy();
    process.env.DATABASE_URL = databaseUrl;
    process.env.JWT_SECRET = "test-jwt";
    const probe = new pg.Client({ connectionString: databaseUrl });
    await probe.connect();
    await waitForSeededDb(probe);
    await probe.end();
    app = await buildApp();
    await app.ready();
  });

  afterAll(async () => {
    await app?.close();
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

  it("TC-BR-19-004: student denied GET /reports/attendance without data leakage", async () => {
    const token = await login(app, "student1@attendly.local");
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/reports/attendance?termId=20000000-0000-4000-8000-000000000001&page=1&pageSize=25",
      headers: { authorization: `Bearer ${token}` },
    });
    expect(response.statusCode).toBe(403);
    const body = response.json() as { data: null; error: { code: string }; meta: unknown };
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
});
