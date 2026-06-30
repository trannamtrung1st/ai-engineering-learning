import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { ErrorCode, RosterImportStatus, SESSION_COOKIE_NAME, UserRole } from "@wecheck/domain";
import { createPool, setPool, closePool, type DbPool } from "../../infra/db.js";
import { runMigrations } from "../../infra/migrate.js";
import { buildApp } from "../../server.js";
import {
  createTestUser,
  SessionStore,
  truncateAuthTables,
} from "../../auth/session-store.js";
import { hashPassword } from "../identity-auth/password-hasher.js";
import { ClassSubjectWriteService } from "./class-subject-write/class-subject-write-service.js";
import { RosterService, truncateRosterTables } from "./roster-service.js";
import { truncateCheckInTables } from "../checkin-qr/check-in-service.js";
import { withIntegrationTestDbReset } from "../../infra/integration-test-lock.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

function buildCsv(rows: string[]): string {
  const header = "institutional_id,display_name,class_code,subject_code";
  return [header, ...rows].join("\n");
}

function multipartPayload(csv: string, boundary = "----wecheck"): {
  payload: string;
  contentType: string;
} {
  const payload =
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="file"; filename="roster.csv"\r\n` +
    `Content-Type: text/csv\r\n\r\n` +
    `${csv}\r\n` +
    `--${boundary}--\r\n`;
  return {
    payload,
    contentType: `multipart/form-data; boundary=${boundary}`,
  };
}

/**
 * Traceability: AC-03 FR-03
 * Cases: TC-AC-03-020 TC-AC-03-021 TC-AC-03-022 TC-AC-03-023
 * TC-FR-03-021 TC-FR-03-022 TC-FR-03-023 TC-FR-03-024 TC-FR-03-025
 * TC-FR-03-026 TC-FR-03-027
 */
describe("class-subject write integration (AC-03, FR-03)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let store: SessionStore;
  let writeService: ClassSubjectWriteService;
  let rosterService: RosterService;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    store = new SessionStore(db);
    writeService = new ClassSubjectWriteService(db);
    rosterService = new RosterService(db);
  });

  after(async () => {
    await app.close();
    await closePool();
  });

  async function resetDb(): Promise<void> {
    await withIntegrationTestDbReset(db, async () => {
      await truncateCheckInTables(db);
      await truncateRosterTables(db);
      await truncateAuthTables(db);
      await db.query("DELETE FROM policy_settings WHERE key = 'preview_seed_version'");
    });
  }

  async function seedAdmin(): Promise<{ userId: string; cookie: string }> {
    const passwordHash = await hashPassword("AdminPass123");
    const userId = randomUUID();
    const institutionalId = `ADMIN-${userId.slice(0, 8)}`;
    await db.query(
      `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, 'Admin User', $3, $4, $5, true)`,
      [userId, institutionalId, `admin-${userId.slice(0, 8)}@example.edu.vn`, passwordHash, UserRole.TrainingOfficeAdmin],
    );
    const session = await store.createSession(userId);
    return { userId, cookie: `${SESSION_COOKIE_NAME}=${session.id}` };
  }

  async function seedInstructor(): Promise<{ userId: string; cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId: "GV2026001",
      displayName: "Instructor One",
      email: "instructor@example.edu.vn",
      role: UserRole.Instructor,
    });
    const session = await store.createSession(userId);
    return { userId, cookie: `${SESSION_COOKIE_NAME}=${session.id}` };
  }

  async function pollBatch(
    batchId: string,
    cookie: string,
  ): Promise<{
    status: string;
    successRows: number;
    errorRows: number;
  }> {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const res = await app.inject({
        method: "GET",
        url: `/api/v1/roster/imports/${batchId}`,
        headers: { cookie },
      });
      const body = res.json<{
        status: string;
        successRows: number;
        errorRows: number;
      }>();
      if (body.status === RosterImportStatus.Completed) {
        return body;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error("import batch did not complete");
  }

  it("POST /classes and POST /subjects persist reference records (TC-AC-03-020, TC-AC-03-021, TC-FR-03-021, TC-FR-03-022, TC-FR-03-024, TC-FR-03-025)", async () => {
    await resetDb();
    const admin = await seedAdmin();

    const classRes = await app.inject({
      method: "POST",
      url: "/api/v1/classes",
      headers: { cookie: admin.cookie },
      payload: { code: "HESD-03", name: "HESD Cohort 03" },
    });
    assert.equal(classRes.statusCode, 201);
    const classBody = classRes.json<{ id: string; code: string; name: string }>();
    assert.match(classBody.id, /^[0-9a-f-]{36}$/i);
    assert.equal(classBody.code, "HESD-03");
    assert.equal(classBody.name, "HESD Cohort 03");

    const subjectRes = await app.inject({
      method: "POST",
      url: "/api/v1/subjects",
      headers: { cookie: admin.cookie },
      payload: { code: "SWE-102", name: "Software Engineering 102" },
    });
    assert.equal(subjectRes.statusCode, 201);
    const subjectBody = subjectRes.json<{ id: string; code: string; name: string }>();
    assert.equal(subjectBody.code, "SWE-102");

    const listClasses = await app.inject({
      method: "GET",
      url: "/api/v1/classes",
      headers: { cookie: admin.cookie },
    });
    assert.ok(
      listClasses
        .json<{ items: { code: string }[] }>()
        .items.some((item) => item.code === "HESD-03"),
    );

    const listSubjects = await app.inject({
      method: "GET",
      url: "/api/v1/subjects",
      headers: { cookie: admin.cookie },
    });
    assert.ok(
      listSubjects
        .json<{ items: { code: string }[] }>()
        .items.some((item) => item.code === "SWE-102"),
    );

    const stored = await db.query<{ code: string }>(
      "SELECT code FROM classes WHERE code = 'HESD-03'",
    );
    assert.equal(stored.rows[0]?.code, "HESD-03");
  });

  it("ClassSubjectWriteService persists uppercase codes (TC-AC-03-020, TC-FR-03-021, TC-FR-03-022)", async () => {
    await resetDb();

    const createdClass = await writeService.createClass("HESD-03", "HESD Cohort 03");
    assert.equal(createdClass.code, "HESD-03");

    const createdSubject = await writeService.createSubject(
      "SWE-102",
      "Software Engineering 102",
    );
    assert.equal(createdSubject.code, "SWE-102");

    const classRow = await db.query<{ code: string; name: string }>(
      "SELECT code, name FROM classes WHERE code = 'HESD-03'",
    );
    assert.equal(classRow.rowCount, 1);
    assert.equal(classRow.rows[0]?.name, "HESD Cohort 03");

    const subjectRow = await db.query<{ code: string }>(
      "SELECT code FROM subjects WHERE code = 'SWE-102'",
    );
    assert.equal(subjectRow.rowCount, 1);
  });

  it("lowercase class code rejected before persist (TC-AC-03-020)", async () => {
    await resetDb();
    const admin = await seedAdmin();

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/classes",
      headers: { cookie: admin.cookie },
      payload: { code: "hesd-99", name: "Invalid Lowercase" },
    });

    assert.equal(response.statusCode, 422);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.ValidationFailed,
    );

    const count = await db.query("SELECT id FROM classes WHERE code = 'hesd-99'");
    assert.equal(count.rowCount, 0);
  });

  it("duplicate class code returns DuplicateClassCode (TC-AC-03-022, TC-FR-03-023)", async () => {
    await resetDb();
    const admin = await seedAdmin();

    await app.inject({
      method: "POST",
      url: "/api/v1/classes",
      headers: { cookie: admin.cookie },
      payload: { code: "HESD-03", name: "HESD Cohort 03" },
    });

    const dup = await app.inject({
      method: "POST",
      url: "/api/v1/classes",
      headers: { cookie: admin.cookie },
      payload: { code: "HESD-03", name: "Different Name" },
    });

    assert.equal(dup.statusCode, 422);
    assert.equal(dup.json<{ errorCode: string }>().errorCode, ErrorCode.DuplicateClassCode);
    assert.match(dup.json<{ message: string }>().message, /Mã lớp đã tồn tại/);

    const count = await db.query("SELECT id FROM classes WHERE code = 'HESD-03'");
    assert.equal(count.rowCount, 1);
  });

  it("duplicate subject code returns DuplicateSubjectCode (TC-AC-03-023, TC-FR-03-026)", async () => {
    await resetDb();
    const admin = await seedAdmin();

    await app.inject({
      method: "POST",
      url: "/api/v1/subjects",
      headers: { cookie: admin.cookie },
      payload: { code: "SWE-102", name: "Software Engineering 102" },
    });

    const dup = await app.inject({
      method: "POST",
      url: "/api/v1/subjects",
      headers: { cookie: admin.cookie },
      payload: { code: "SWE-102", name: "Duplicate attempt" },
    });

    assert.equal(dup.statusCode, 422);
    assert.equal(
      dup.json<{ errorCode: string }>().errorCode,
      ErrorCode.DuplicateSubjectCode,
    );

    const count = await db.query("SELECT id FROM subjects WHERE code = 'SWE-102'");
    assert.equal(count.rowCount, 1);
  });

  it("instructor and student denied POST /classes and POST /subjects (TC-FR-03-027)", async () => {
    await resetDb();
    const instructor = await seedInstructor();
    const studentId = await createTestUser(db, {
      institutionalId: "SV-REF-DENY",
      displayName: "Student",
      email: "student-ref-deny@example.edu.vn",
      role: UserRole.Student,
    });
    const studentSession = await store.createSession(studentId);
    const studentCookie = `${SESSION_COOKIE_NAME}=${studentSession.id}`;

    const body = { code: "HESD-99", name: "Denied Class" };

    const instructorClass = await app.inject({
      method: "POST",
      url: "/api/v1/classes",
      headers: { cookie: instructor.cookie },
      payload: body,
    });
    assert.equal(instructorClass.statusCode, 403);

    const studentSubject = await app.inject({
      method: "POST",
      url: "/api/v1/subjects",
      headers: { cookie: studentCookie },
      payload: { code: "SWE-199", name: "Denied Subject" },
    });
    assert.equal(studentSubject.statusCode, 403);

    const classes = await db.query("SELECT id FROM classes WHERE code = 'HESD-99'");
    assert.equal(classes.rowCount, 0);
  });

  it("created class and subject accepted by CSV import (TC-FR-03-024, AC-03d)", async () => {
    await resetDb();
    const admin = await seedAdmin();

    await app.inject({
      method: "POST",
      url: "/api/v1/classes",
      headers: { cookie: admin.cookie },
      payload: { code: "HESD-03", name: "HESD Cohort 03" },
    });
    await app.inject({
      method: "POST",
      url: "/api/v1/subjects",
      headers: { cookie: admin.cookie },
      payload: { code: "SWE-102", name: "Software Engineering 102" },
    });

    const csv = buildCsv(["SV2027101,New Student,HESD-03,SWE-102"]);
    const { payload, contentType } = multipartPayload(csv);
    const importRes = await app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
      headers: { cookie: admin.cookie, "content-type": contentType },
      payload,
    });
    const { batchId } = importRes.json<{ batchId: string }>();
    const batch = await pollBatch(batchId, admin.cookie);
    assert.equal(batch.successRows, 1);
    assert.equal(batch.errorRows, 0);

    const summary = await rosterService.getImportBatch(batchId);
    assert.equal(summary?.successRows, 1);
  });
});
