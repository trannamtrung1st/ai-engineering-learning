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
import { RosterService, truncateRosterTables } from "./roster-service.js";
import { truncateCheckInTables } from "../checkin-qr/check-in-service.js";
import { RosterRowErrorCode } from "./csv-validator.js";
import { withIntegrationTestDbReset } from "../../infra/integration-test-lock.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

const CLASS_HESD_01 = "10000000-0000-4000-8000-000000000201";
const CLASS_HESD_02 = "10000000-0000-4000-8000-000000000202";
const SUBJECT_SWE_101 = "20000000-0000-4000-8000-000000000301";

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
 * Traceability: AC-03 FR-03 BR-08
 * Cases: TC-AC-03-002 TC-AC-03-003 TC-AC-03-004 TC-AC-03-005 TC-AC-03-006
 * TC-AC-03-007 TC-AC-03-008 TC-AC-03-009 TC-AC-03-010 TC-AC-03-012 TC-AC-03-013
 * TC-AC-03-014 TC-AC-03-015 TC-AC-03-020 TC-AC-03-021 TC-AC-03-022 TC-AC-03-023
 * TC-FR-03-002 TC-FR-03-016 TC-FR-03-017 TC-FR-03-021 TC-FR-03-022 TC-FR-03-023
 * TC-FR-03-024 TC-FR-03-025 TC-FR-03-026 TC-FR-03-027
 */
describe("roster-enrollment integration (AC-03, FR-03, BR-08)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let store: SessionStore;
  let rosterService: RosterService;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    store = new SessionStore(db);
    rosterService = new RosterService(db);
  });

  after(async () => {
    await app.close();
    await closePool();
  });

  async function resetDb(afterTruncate?: () => Promise<void>): Promise<void> {
    await withIntegrationTestDbReset(db, async () => {
      await truncateCheckInTables(db);
      await truncateRosterTables(db);
      await truncateAuthTables(db);
      await db.query("DELETE FROM policy_settings WHERE key = 'preview_seed_version'");
      if (afterTruncate) await afterTruncate();
    });
  }

  async function seedReferenceData(): Promise<void> {
    await db.query(
      `INSERT INTO classes (id, code, name) VALUES
       ($1, 'HESD-01', 'HESD Cohort A'),
       ($2, 'HESD-02', 'HESD Cohort B')
       ON CONFLICT (id) DO NOTHING`,
      [CLASS_HESD_01, CLASS_HESD_02],
    );
    await db.query(
      `INSERT INTO subjects (id, code, name) VALUES ($1, 'SWE-101', 'Software Engineering 101')
       ON CONFLICT (id) DO NOTHING`,
      [SUBJECT_SWE_101],
    );
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

  async function seedInstructor(
    assignedToHesd01 = true,
  ): Promise<{ userId: string; cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId: "GV2026001",
      displayName: "Instructor One",
      email: "instructor@example.edu.vn",
      role: UserRole.Instructor,
    });
    if (assignedToHesd01) {
      await db.query(
        `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
         VALUES ($1, $2, $3)`,
        [userId, CLASS_HESD_01, SUBJECT_SWE_101],
      );
    }
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
    errorDetails: { rowNumber: number; errorCode: string }[];
  }> {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const response = await app.inject({
        method: "GET",
        url: `/api/v1/roster/imports/${batchId}`,
        headers: { cookie },
      });
      const body = response.json<{
        status: string;
        successRows: number;
        errorRows: number;
        errorDetails: { rowNumber: number; errorCode: string }[];
      }>();
      if (body.status === RosterImportStatus.Completed) {
        return body;
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error(`Batch ${batchId} did not complete`);
  }

  it("RosterService.importCsv persists enrollments in Postgres (TC-AC-03-002, TC-FR-03-002, FR-03)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();

    const csv = Buffer.from(
      buildCsv([
        "SV2026101,Student One,HESD-01,SWE-101",
        "SV2026102,Student Two,HESD-01,SWE-101",
      ]),
      "utf8",
    );

    const summary = await rosterService.importCsv(csv, {
      uploadedById: admin.userId,
      fileName: "roster.csv",
    });

    assert.equal(summary.successRows, 2);
    assert.equal(summary.errorRows, 0);
    assert.equal(summary.status, RosterImportStatus.Completed);

    const count = await rosterService.getEnrollments(
      CLASS_HESD_01,
      SUBJECT_SWE_101,
      admin.userId,
      UserRole.TrainingOfficeAdmin,
    );
    assert.equal(count.totalCount, 2);
  });

  it("duplicate enrollment rejected with DuplicateEnrollment (TC-AC-03-005, TC-FR-03-005)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();

    const passwordHash = await hashPassword("StudentPass8");
    await db.query(
      `INSERT INTO users (institutional_id, display_name, email, password_hash, role, active)
       VALUES ('SV2026001', 'Existing Student', 'sv2026001@example.edu.vn', $1, $2, true)`,
      [passwordHash, UserRole.Student],
    );

    await rosterService.importCsv(
      Buffer.from(
        buildCsv(["SV2026001,Existing Student,HESD-01,SWE-101"]),
        "utf8",
      ),
      { uploadedById: admin.userId, fileName: "first.csv" },
    );

    const second = await rosterService.importCsv(
      Buffer.from(
        buildCsv(["SV2026001,Existing Student,HESD-01,SWE-101"]),
        "utf8",
      ),
      { uploadedById: admin.userId, fileName: "dup.csv" },
    );

    assert.equal(second.successRows, 0);
    assert.equal(second.errorRows, 1);
    assert.equal(second.errorDetails[0]?.errorCode, RosterRowErrorCode.DuplicateEnrollment);

    const count = await db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM enrollments e
       INNER JOIN users u ON u.id = e.student_id
       WHERE u.institutional_id = 'SV2026001'`,
    );
    assert.equal(count.rows[0]?.count, "1");
  });

  it("unknown class_code rejected with UnknownClassCode (TC-AC-03-014, TC-FR-03-014)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();

    const summary = await rosterService.importCsv(
      Buffer.from(
        buildCsv(["SV2026103,Student Three,NONEXIST-99,SWE-101"]),
        "utf8",
      ),
      { uploadedById: admin.userId, fileName: "bad-class.csv" },
    );

    assert.equal(summary.successRows, 0);
    assert.equal(summary.errorRows, 1);
    assert.equal(summary.errorDetails[0]?.errorCode, RosterRowErrorCode.UnknownClassCode);

    const enrollments = await db.query("SELECT id FROM enrollments");
    assert.equal(enrollments.rowCount, 0);
  });

  it("dryRun validates without persisting enrollments (TC-AC-03-015, TC-FR-03-015)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();

    const csv = Buffer.from(
      buildCsv([
        "SV2026201,Alpha,HESD-01,SWE-101",
        "SV2026202,Beta,HESD-01,SWE-101",
        "SV2026203,Gamma,HESD-01,SWE-101",
      ]),
      "utf8",
    );

    const dry = await rosterService.importCsv(csv, {
      uploadedById: admin.userId,
      fileName: "dry.csv",
      dryRun: true,
    });
    assert.equal(dry.successRows, 3);

    const before = await db.query("SELECT id FROM enrollments");
    assert.equal(before.rowCount, 0);

    const committed = await rosterService.importCsv(csv, {
      uploadedById: admin.userId,
      fileName: "commit.csv",
    });
    assert.equal(committed.successRows, 3);

    const after = await db.query("SELECT id FROM enrollments");
    assert.equal(after.rowCount, 3);
  });

  it("POST /roster/import returns 202 Processing envelope (TC-AC-03-003, TC-FR-03-003)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();
    const csv = buildCsv(["SV2026301,Student A,HESD-01,SWE-101"]);
    const { payload, contentType } = multipartPayload(csv);

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
      headers: { cookie: admin.cookie, "content-type": contentType },
      payload,
    });

    assert.equal(response.statusCode, 202);
    const body = response.json<{ batchId: string; status: string; message: string }>();
    assert.match(body.batchId, /^[0-9a-f-]{36}$/i);
    assert.equal(body.status, RosterImportStatus.Processing);
    assert.match(body.message, /Đang xử lý/);
    assert.equal("enrollments" in body, false);
    await pollBatch(body.batchId, admin.cookie);
  });

  it("mixed valid and duplicate CSV import via HTTP (TC-AC-03-004, TC-FR-03-004)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();
    const csv = buildCsv([
      "SV2026401,First,HESD-01,SWE-101",
      "SV2026402,Second,HESD-01,SWE-101",
      "SV2026401,First Duplicate,HESD-01,SWE-101",
    ]);
    const { payload, contentType } = multipartPayload(csv);

    const importRes = await app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
      headers: { cookie: admin.cookie, "content-type": contentType },
      payload,
    });
    const { batchId } = importRes.json<{ batchId: string }>();

    const batch = await pollBatch(batchId, admin.cookie);
    assert.equal(batch.successRows, 2);
    assert.equal(batch.errorRows, 1);
    assert.equal(batch.errorDetails[0]?.errorCode, RosterRowErrorCode.DuplicateEnrollment);

    const listRes = await app.inject({
      method: "GET",
      url: `/api/v1/enrollments?classId=${CLASS_HESD_01}&subjectId=${SUBJECT_SWE_101}`,
      headers: { cookie: admin.cookie },
    });
    assert.equal(listRes.json<{ totalCount: number }>().totalCount, 2);
  });

  it("instructor denied GET /enrollments for unassigned class (TC-AC-03-006, TC-AC-03-007, TC-FR-03-006, TC-FR-03-007, BR-08)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();
    await rosterService.importCsv(
      Buffer.from(buildCsv(["SV2026501,Student,HESD-02,SWE-101"]), "utf8"),
      { uploadedById: admin.userId, fileName: "hesd02.csv" },
    );

    const instructor = await seedInstructor(true);
    const response = await app.inject({
      method: "GET",
      url: `/api/v1/enrollments?classId=${CLASS_HESD_02}&subjectId=${SUBJECT_SWE_101}`,
      headers: { cookie: instructor.cookie },
    });

    assert.equal(response.statusCode, 403);
    assert.equal(response.json<{ errorCode: string }>().errorCode, ErrorCode.Forbidden);
    assert.equal("enrollments" in response.json(), false);
  });

  it("instructor and student denied POST /roster/import (TC-AC-03-008, TC-FR-03-008)", async () => {
    await resetDb(seedReferenceData);
    const csv = buildCsv(["SV2026601,Student,HESD-01,SWE-101"]);
    const { payload, contentType } = multipartPayload(csv);

    const instructor = await seedInstructor(true);
    const instructorRes = await app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
      headers: { cookie: instructor.cookie, "content-type": contentType },
      payload,
    });
    assert.equal(instructorRes.statusCode, 403);

    const studentId = await createTestUser(db, {
      institutionalId: "SV-STUDENT",
      displayName: "Student",
      email: "student-roster@example.edu.vn",
      role: UserRole.Student,
    });
    const studentSession = await store.createSession(studentId);
    const studentRes = await app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
      headers: {
        cookie: `${SESSION_COOKIE_NAME}=${studentSession.id}`,
        "content-type": contentType,
      },
      payload,
    });
    assert.equal(studentRes.statusCode, 403);

    const batches = await db.query("SELECT id FROM roster_import_batches");
    assert.equal(batches.rowCount, 0);
  });

  it("GET /roster/imports/:batchId returns summary with errorDetails (TC-AC-03-009, TC-FR-03-009)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();
    const csv = buildCsv([
      "SV2026701,Valid,HESD-01,SWE-101",
      "SV2026701,Duplicate,HESD-01,SWE-101",
    ]);
    const { payload, contentType } = multipartPayload(csv);

    const importRes = await app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
      headers: { cookie: admin.cookie, "content-type": contentType },
      payload,
    });
    const { batchId } = importRes.json<{ batchId: string }>();
    const batch = await pollBatch(batchId, admin.cookie);

    assert.equal(batch.status, RosterImportStatus.Completed);
    assert.equal(batch.successRows, 1);
    assert.equal(batch.errorRows, 1);
    assert.ok(batch.errorDetails[0]?.rowNumber);
    assert.ok(batch.errorDetails[0]?.errorCode);
  });

  it("GET /enrollments returns roster for assigned instructor (TC-AC-03-010, TC-FR-03-010)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();
    await rosterService.importCsv(
      Buffer.from(buildCsv(["SV2026801,Nguyen Van A,HESD-01,SWE-101"]), "utf8"),
      { uploadedById: admin.userId, fileName: "one.csv" },
    );

    const instructor = await seedInstructor(true);
    const response = await app.inject({
      method: "GET",
      url: `/api/v1/enrollments?classId=${CLASS_HESD_01}&subjectId=${SUBJECT_SWE_101}`,
      headers: { cookie: instructor.cookie },
    });

    assert.equal(response.statusCode, 200);
    const body = response.json<{
      class: { code: string };
      subject: { code: string };
      enrollments: { enrollmentId: string; student: { institutionalId: string } }[];
      totalCount: number;
    }>();
    assert.equal(body.class.code, "HESD-01");
    assert.equal(body.subject.code, "SWE-101");
    assert.equal(body.totalCount, 1);
    assert.equal(body.enrollments[0]?.student.institutionalId, "SV2026801");
  });

  it("POST /roster/import without file returns 422 InvalidFile (TC-AC-03-013, TC-FR-03-013)", async () => {
    await resetDb();
    const admin = await seedAdmin();
    const boundary = "----empty";
    const payload = `--${boundary}--\r\n`;

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
      headers: {
        cookie: admin.cookie,
        "content-type": `multipart/form-data; boundary=${boundary}`,
      },
      payload,
    });

    assert.equal(response.statusCode, 422);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.InvalidFile,
    );
  });

  it("RosterImportBatch transitions Processing to Completed (TC-FR-03-016)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();
    const csv = buildCsv([
      "SV2026901,One,HESD-01,SWE-101",
      "SV2026902,Two,HESD-01,SWE-101",
    ]);
    const { payload, contentType } = multipartPayload(csv);

    const importRes = await app.inject({
      method: "POST",
      url: "/api/v1/roster/import",
      headers: { cookie: admin.cookie, "content-type": contentType },
      payload,
    });
    const { batchId } = importRes.json<{ batchId: string }>();

    const processing = await db.query<{ status: string }>(
      "SELECT status FROM roster_import_batches WHERE id = $1",
      [batchId],
    );
    assert.equal(processing.rows[0]?.status, RosterImportStatus.Processing);

    const batch = await pollBatch(batchId, admin.cookie);
    assert.equal(batch.status, RosterImportStatus.Completed);
    assert.equal(batch.successRows, 2);
    assert.equal(batch.errorRows, 0);

    const completed = await db.query<{ completed_at: Date | null }>(
      "SELECT completed_at FROM roster_import_batches WHERE id = $1",
      [batchId],
    );
    assert.ok(completed.rows[0]?.completed_at);
  });

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
    const instructor = await seedInstructor(false);
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

  it("student denied GET /enrollments with 403 (TC-FR-03-017)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();
    await rosterService.importCsv(
      Buffer.from(buildCsv(["SV2027001,Student,HESD-01,SWE-101"]), "utf8"),
      { uploadedById: admin.userId, fileName: "one.csv" },
    );

    const imported = await db.query<{ id: string }>(
      "SELECT id FROM users WHERE institutional_id = 'SV2027001'",
    );
    const studentSession = await store.createSession(imported.rows[0]!.id);

    const response = await app.inject({
      method: "GET",
      url: `/api/v1/enrollments?classId=${CLASS_HESD_01}&subjectId=${SUBJECT_SWE_101}`,
      headers: { cookie: `${SESSION_COOKIE_NAME}=${studentSession.id}` },
    });

    assert.equal(response.statusCode, 403);
    assert.equal(response.json<{ errorCode: string }>().errorCode, ErrorCode.Forbidden);
    assert.equal("enrollments" in response.json(), false);
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
  });
});
