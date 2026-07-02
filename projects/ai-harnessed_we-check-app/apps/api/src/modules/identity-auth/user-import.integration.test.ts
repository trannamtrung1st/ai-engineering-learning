import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { ErrorCode, SESSION_COOKIE_NAME, UserImportStatus, UserRole } from "@wecheck/domain";
import { createPool, setPool, closePool, type DbPool } from "../../infra/db.js";
import { runMigrations } from "../../infra/migrate.js";
import { buildApp } from "../../server.js";
import { truncateAuthTables } from "../../auth/session-store.js";
import { withIntegrationTestDbReset } from "../../infra/integration-test-lock.js";
import { hashPassword, isPasswordHash } from "./password-hasher.js";
import { UserRepository } from "./user-repository.js";
import { UserImportService } from "./user-import-service.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

function buildUserCsv(rows: string[]): string {
  const header = "institutional_id,display_name,email,role,active";
  return [header, ...rows].join("\n");
}

function multipartUserPayload(csv: string, boundary = "----wecheck-users"): {
  payload: string;
  contentType: string;
} {
  const payload =
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="file"; filename="users.csv"\r\n` +
    `Content-Type: text/csv\r\n\r\n` +
    `${csv}\r\n` +
    `--${boundary}--\r\n`;
  return {
    payload,
    contentType: `multipart/form-data; boundary=${boundary}`,
  };
}

/**
 * Traceability: AC-01 FR-01 NFR-11 NFR-14
 * Cases: TC-FR-01-020 TC-FR-01-021 TC-FR-01-022 TC-FR-01-023 TC-FR-01-025
 * TC-NFR-14-022 TC-NFR-14-023 TC-NFR-11-010
 */
describe("user CSV import integration (AC-01, FR-01, NFR-11, NFR-14)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let users: UserRepository;
  let userImportService: UserImportService;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    users = new UserRepository(db);
    userImportService = new UserImportService(db, users);
  });

  after(async () => {
    await app.close();
    await closePool();
  });

  async function resetDb(): Promise<void> {
    await withIntegrationTestDbReset(db, async () => {
      await truncateAuthTables(db);
    });
  }

  async function seedAdmin(): Promise<{ email: string; password: string }> {
    const password = "AdminPass123";
    const passwordHash = await hashPassword(password);
    const userId = randomUUID();
    await db.query(
      `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, $6, true)`,
      [
        userId,
        "ADMIN999",
        "Admin User",
        `admin-${userId.slice(0, 8)}@example.edu.vn`,
        passwordHash,
        UserRole.TrainingOfficeAdmin,
      ],
    );
    return { email: `admin-${userId.slice(0, 8)}@example.edu.vn`, password };
  }

  async function seedStudent(
    institutionalId: string,
    email: string,
    password = "StudentPass8",
  ): Promise<{ cookie: string }> {
    const passwordHash = await hashPassword(password);
    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, true)`,
      [institutionalId, "Student", email, passwordHash, UserRole.Student],
    );
    const loginRes = await app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email, password },
    });
    const setCookie = loginRes.headers["set-cookie"];
    const cookieHeader = Array.isArray(setCookie) ? setCookie[0] : setCookie;
    const match = cookieHeader?.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`));
    const sessionId = match?.[1] ?? "";
    return { cookie: `${SESSION_COOKIE_NAME}=${sessionId}` };
  }

  async function loginAs(
    email: string,
    password: string,
  ): Promise<{ cookie: string }> {
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/auth/login",
      payload: { email, password },
    });
    assert.equal(response.statusCode, 200);
    const setCookie = response.headers["set-cookie"];
    const cookieHeader = Array.isArray(setCookie) ? setCookie[0] : setCookie;
    const match = cookieHeader?.match(new RegExp(`${SESSION_COOKIE_NAME}=([^;]+)`));
    const sessionId = match?.[1] ?? "";
    return { cookie: `${SESSION_COOKIE_NAME}=${sessionId}` };
  }

  async function pollUserBatch(
    batchId: string,
    cookie: string,
  ): Promise<{
    status: string;
    createdCount: number;
    updatedCount: number;
    successRows: number;
    errorRows: number;
    totalRows: number;
    errorDetails: { rowNumber: number; errorCode: string; field?: string }[];
  }> {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const response = await app.inject({
        method: "GET",
        url: `/api/v1/users/imports/${batchId}`,
        headers: { cookie },
      });
      const body = response.json<{
        status: string;
        createdCount: number;
        updatedCount: number;
        successRows: number;
        errorRows: number;
        totalRows: number;
        errorDetails: { rowNumber: number; errorCode: string; field?: string }[];
      }>();
      if (body.status === UserImportStatus.Completed) {
        return body;
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error(`User import batch ${batchId} did not complete`);
  }

  it("POST /users/import upsert creates and updates by institutional_id (TC-FR-01-020, AC-01d)", async () => {
    await resetDb();
    const admin = await seedAdmin();
    const adminSession = await loginAs(admin.email, admin.password);

    const existingHash = await hashPassword("ExistingPass8");
    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, true)`,
      [
        "SV2026100",
        "Old Name",
        "old6100@example.edu.vn",
        existingHash,
        UserRole.Student,
      ],
    );

    const csv = buildUserCsv([
      "SV2026101,New Student,new6101@example.edu.vn,Student,true",
      "SV2026100,Updated Name,updated6100@example.edu.vn,Instructor,false",
    ]);
    const { payload, contentType } = multipartUserPayload(csv);

    const importRes = await app.inject({
      method: "POST",
      url: "/api/v1/users/import",
      headers: { cookie: adminSession.cookie, "content-type": contentType },
      payload,
    });
    assert.equal(importRes.statusCode, 202);
    const { batchId } = importRes.json<{ batchId: string }>();

    const batch = await pollUserBatch(batchId, adminSession.cookie);
    assert.equal(batch.status, UserImportStatus.Completed);
    assert.equal(batch.createdCount, 1);
    assert.equal(batch.updatedCount, 1);

    const newRow = await db.query<{
      display_name: string;
      role: string;
      active: boolean;
      password_hash: string;
    }>(
      "SELECT display_name, role, active, password_hash FROM users WHERE institutional_id = $1",
      ["SV2026101"],
    );
    assert.equal(newRow.rows[0]?.display_name, "New Student");
    assert.equal(newRow.rows[0]?.role, UserRole.Student);
    assert.equal(newRow.rows[0]?.active, true);
    assert.ok(isPasswordHash(newRow.rows[0]?.password_hash ?? ""));

    const updatedRow = await db.query<{
      display_name: string;
      email: string;
      role: string;
      active: boolean;
      password_hash: string;
    }>(
      "SELECT display_name, email, role, active, password_hash FROM users WHERE institutional_id = $1",
      ["SV2026100"],
    );
    assert.equal(updatedRow.rows[0]?.display_name, "Updated Name");
    assert.equal(updatedRow.rows[0]?.email, "updated6100@example.edu.vn");
    assert.equal(updatedRow.rows[0]?.role, UserRole.Instructor);
    assert.equal(updatedRow.rows[0]?.active, false);
    assert.equal(updatedRow.rows[0]?.password_hash, existingHash);
  });

  it("CSV import idempotent when profile unchanged (TC-FR-01-021, AC-01e)", async () => {
    await resetDb();
    const admin = await seedAdmin();

    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, true)`,
      [
        "SV2026200",
        "Same Profile",
        "same6200@example.edu.vn",
        await hashPassword("SamePass8"),
        UserRole.Student,
      ],
    );

    const csv = buildUserCsv([
      "SV2026200,Same Profile,same6200@example.edu.vn,Student,true",
    ]);
    const summary = await userImportService.importCsv(
      Buffer.from(csv, "utf8"),
      { uploadedById: (await users.findByEmail(admin.email))!.id, fileName: "same.csv" },
    );

    assert.equal(summary.successRows, 1);
    assert.equal(summary.updatedCount, 0);
    assert.equal(summary.createdCount, 0);

    const count = await db.query<{ count: string }>(
      "SELECT COUNT(*)::text AS count FROM users WHERE institutional_id = $1",
      ["SV2026200"],
    );
    assert.equal(count.rows[0]?.count, "1");
  });

  it("CSV import rejects DuplicateEmail for different institutional_id (TC-FR-01-022, AC-01g)", async () => {
    await resetDb();
    const admin = await seedAdmin();
    const adminSession = await loginAs(admin.email, admin.password);

    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, true)`,
      [
        "SV2026300",
        "Email Owner",
        "taken@example.edu.vn",
        await hashPassword("OwnerPass8"),
        UserRole.Student,
      ],
    );

    const csv = buildUserCsv([
      "SV2026301,Valid New,valid6301@example.edu.vn,Student,true",
      "SV2026302,Email Thief,taken@example.edu.vn,Student,true",
    ]);
    const { payload, contentType } = multipartUserPayload(csv);

    const importRes = await app.inject({
      method: "POST",
      url: "/api/v1/users/import",
      headers: { cookie: adminSession.cookie, "content-type": contentType },
      payload,
    });
    const { batchId } = importRes.json<{ batchId: string }>();
    const batch = await pollUserBatch(batchId, adminSession.cookie);

    assert.equal(batch.createdCount, 1);
    assert.equal(batch.errorRows, 1);
    assert.equal(batch.errorDetails[0]?.errorCode, ErrorCode.DuplicateEmail);

    const thief = await db.query(
      "SELECT id FROM users WHERE institutional_id = $1",
      ["SV2026302"],
    );
    assert.equal(thief.rowCount, 0);
  });

  it("CSV import accepts institutional_id with underscore and period (TC-FR-01-023, AC-01f)", async () => {
    await resetDb();
    const admin = await seedAdmin();
    const adminSession = await loginAs(admin.email, admin.password);

    const csv = buildUserCsv([
      "SV_2026.002,Period Student,period002@example.edu.vn,Student,true",
    ]);
    const { payload, contentType } = multipartUserPayload(csv);

    const importRes = await app.inject({
      method: "POST",
      url: "/api/v1/users/import",
      headers: { cookie: adminSession.cookie, "content-type": contentType },
      payload,
    });
    assert.equal(importRes.statusCode, 202);
    const { batchId } = importRes.json<{ batchId: string }>();
    const batch = await pollUserBatch(batchId, adminSession.cookie);
    assert.equal(batch.createdCount, 1);

    const row = await db.query<{ institutional_id: string }>(
      "SELECT institutional_id FROM users WHERE institutional_id = $1",
      ["SV_2026.002"],
    );
    assert.equal(row.rowCount, 1);
    assert.equal(row.rows[0]?.institutional_id, "SV_2026.002");
  });

  it("POST /users/import returns 202 with batch envelope (TC-FR-01-025, AC-01d)", async () => {
    await resetDb();
    const admin = await seedAdmin();
    const adminSession = await loginAs(admin.email, admin.password);

    const csv = buildUserCsv([
      "SV-IMPORT-01,Import One,import01@example.edu.vn,Student,true",
    ]);
    const { payload, contentType } = multipartUserPayload(csv);

    const importRes = await app.inject({
      method: "POST",
      url: "/api/v1/users/import",
      headers: { cookie: adminSession.cookie, "content-type": contentType },
      payload,
    });
    assert.equal(importRes.statusCode, 202);
    const body = importRes.json<{
      batchId: string;
      status: string;
      message: string;
    }>();
    assert.ok(body.batchId);
    assert.equal(body.status, UserImportStatus.Processing);
    assert.match(body.message, /Đang xử lý/);

    const batch = await pollUserBatch(body.batchId, adminSession.cookie);
    assert.equal(batch.status, UserImportStatus.Completed);
    assert.equal(typeof batch.totalRows, "number");
    assert.equal(typeof batch.createdCount, "number");
    assert.equal(typeof batch.updatedCount, "number");
    assert.ok(Array.isArray(batch.errorDetails));
  });

  it("POST /users/import create row persists bcrypt hash (TC-NFR-14-022, AC-01d, NFR-14)", async () => {
    await resetDb();
    const admin = await seedAdmin();
    const adminUser = await users.findByEmail(admin.email);

    const csv = buildUserCsv([
      "SV2026401,Import Create,import6401@example.edu.vn,Student,true",
    ]);
    const summary = await userImportService.importCsv(
      Buffer.from(csv, "utf8"),
      { uploadedById: adminUser!.id, fileName: "create.csv" },
    );

    assert.equal(summary.createdCount, 1);
    assert.equal("password" in summary, false);
    assert.equal("initialPassword" in summary, false);

    const row = await db.query<{ password_hash: string }>(
      "SELECT password_hash FROM users WHERE institutional_id = $1",
      ["SV2026401"],
    );
    const hash = row.rows[0]?.password_hash ?? "";
    assert.ok(isPasswordHash(hash));
    assert.notEqual(hash, "");
  });

  it("GET /users/imports/:batchId excludes password fields (TC-NFR-14-023, AC-01d, NFR-14)", async () => {
    await resetDb();
    const admin = await seedAdmin();
    const adminSession = await loginAs(admin.email, admin.password);

    const csv = buildUserCsv([
      "SV2026501,Batch Poll,batch6501@example.edu.vn,Student,true",
    ]);
    const { payload, contentType } = multipartUserPayload(csv);
    const importRes = await app.inject({
      method: "POST",
      url: "/api/v1/users/import",
      headers: { cookie: adminSession.cookie, "content-type": contentType },
      payload,
    });
    const { batchId } = importRes.json<{ batchId: string }>();
    const batch = await pollUserBatch(batchId, adminSession.cookie);

    const getRes = await app.inject({
      method: "GET",
      url: `/api/v1/users/imports/${batchId}`,
      headers: { cookie: adminSession.cookie },
    });
    assert.equal(getRes.statusCode, 200);
    const body = getRes.json<Record<string, unknown>>();
    assert.equal(body.status, UserImportStatus.Completed);
    assert.equal(batch.createdCount, 1);
    assert.equal("password" in body, false);
    assert.equal("passwordHash" in body, false);
    assert.equal("initialPassword" in body, false);
  });

  it("Student denied POST /users/import (TC-NFR-11-010, NFR-11)", async () => {
    await resetDb();
    const student = await seedStudent("SV2026601", "student6601@example.edu.vn");
    const csv = buildUserCsv([
      "SV2026602,Blocked,blocked6602@example.edu.vn,Student,true",
    ]);
    const { payload, contentType } = multipartUserPayload(csv);

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/users/import",
      headers: { cookie: student.cookie, "content-type": contentType },
      payload,
    });
    assert.equal(response.statusCode, 403);
    assert.equal(response.json<{ errorCode: string }>().errorCode, ErrorCode.Forbidden);
  });
});
