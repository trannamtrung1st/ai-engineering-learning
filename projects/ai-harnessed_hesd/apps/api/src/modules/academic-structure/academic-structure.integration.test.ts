/**
 * Traceability: FR-01 FR-03 FR-04 FR-06 FR-10 FR-17 BR-06 AC-07
 * TC-FR-01-002 TC-FR-01-007 TC-FR-04-001 TC-FR-04-003 TC-FR-04-004 TC-FR-06-001 TC-FR-06-005
 * TC-BR-06-002 TC-AC-07-002
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
  term: "20000000-0000-4000-8000-000000000001",
  course: "30000000-0000-4000-8000-000000000001",
  room: "40000000-0000-4000-8000-000000000001",
  section: "50000000-0000-4000-8000-000000000001",
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

describe("M02 academic structure module — FR-01 FR-04 FR-06 BR-06 AC-07", () => {
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
    app = await buildApp();
    await app.ready();
    pool = new pg.Pool({ connectionString: databaseUrl });
  });

  afterAll(async () => {
    await app?.close();
    await pool?.end().catch(() => undefined);
  });

  it("TC-FR-01-002: term persists and class section enforces term FK", async () => {
    const token = await login(app, "academic-admin@attendly.local");
    const termCode = `T-${randomUUID().slice(0, 8)}`;

    const createTerm = await app.inject({
      method: "POST",
      url: "/api/v1/terms",
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        code: termCode,
        name: "Integration Term",
        startDate: "2026-08-01",
        endDate: "2026-12-31",
        isActive: true,
      },
    });
    expect(createTerm.statusCode).toBe(200);
    const termBody = createTerm.json() as { data: { id: string; code: string } };
    const termId = termBody.data.id;

    const dbTerm = await pool.query(
      `SELECT code, name, is_active FROM terms WHERE id = $1`,
      [termId],
    );
    expect(dbTerm.rows[0]?.code).toBe(termCode);

    const createSection = await app.inject({
      method: "POST",
      url: "/api/v1/class-sections",
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        sectionCode: `SEC-${randomUUID().slice(0, 8)}`,
        termId,
        courseId: SEED.course,
        lecturerUserId: SEED.lecturer,
        defaultRoomId: SEED.room,
      },
    });
    expect(createSection.statusCode).toBe(200);

    const invalidSection = await app.inject({
      method: "POST",
      url: "/api/v1/class-sections",
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        sectionCode: `BAD-${randomUUID().slice(0, 8)}`,
        termId: randomUUID(),
        courseId: SEED.course,
        lecturerUserId: SEED.lecturer,
      },
    });
    expect(invalidSection.statusCode).toBe(400);
  });

  it("TC-FR-01-007: deactivate term via PATCH isActive false", async () => {
    const token = await login(app, "academic-admin@attendly.local");
    const termCode = `D-${randomUUID().slice(0, 8)}`;

    const created = await app.inject({
      method: "POST",
      url: "/api/v1/terms",
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        code: termCode,
        name: "Deactivate Term",
        startDate: "2026-08-01",
        endDate: "2026-12-31",
        isActive: true,
      },
    });
    const termId = (created.json() as { data: { id: string } }).data.id;

    const patched = await app.inject({
      method: "PATCH",
      url: `/api/v1/terms/${termId}`,
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: { isActive: false },
    });
    expect(patched.statusCode).toBe(200);

    const activeList = await app.inject({
      method: "GET",
      url: "/api/v1/terms?activeOnly=true",
      headers: { authorization: `Bearer ${token}` },
    });
    const activeIds = (
      activeList.json() as { data: { id: string }[] }
    ).data.map((row) => row.id);
    expect(activeIds).not.toContain(termId);
  });

  it("TC-FR-04-001 TC-FR-04-003: enrollment import accepts valid rows and reports rejections", async () => {
    const token = await login(app, "academic-admin@attendly.local");
    const sectionId = randomUUID();

    await pool.query(
      `
      INSERT INTO class_sections (
        id, section_code, term_id, course_id, lecturer_user_id, default_room_id, is_active
      )
      VALUES ($1, $2, $3, $4, $5, $6, true)
      `,
      [sectionId, `IMP-${randomUUID().slice(0, 8)}`, SEED.term, SEED.course, SEED.lecturer, SEED.room],
    );

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/enrollments/import",
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        classSectionId: sectionId,
        rows: [
          { studentCode: "SV001" },
          { studentCode: "UNKNOWN-CODE" },
          { studentCode: "" },
          { studentCode: "SV002" },
          { studentCode: "SV002" },
        ],
      },
    });

    expect(response.statusCode).toBe(200);
    const body = response.json() as {
      data: {
        acceptedRows: number;
        rejectedRows: { rowNumber: number; code: string }[];
      };
    };
    expect(body.data.acceptedRows).toBe(2);
    expect(body.data.rejectedRows).toHaveLength(3);
    expect(body.data.rejectedRows.some((r) => r.code === "StudentNotFound")).toBe(true);

    const enrolled = await pool.query(
      `
      SELECT COUNT(*)::int AS count
      FROM enrollments e
      JOIN student_profiles sp ON sp.user_id = e.student_user_id
      WHERE e.class_section_id = $1 AND e.status = 'Active'
      `,
      [sectionId],
    );
    expect(enrolled.rows[0]?.count).toBe(2);
  });

  it("TC-FR-04-004 TC-BR-06-002 TC-AC-07-002: isStudentEnrolled reflects add/remove", async () => {
    const { isStudentEnrolled, createAcademicRepository } = await import("./repository.js");
    const repo = createAcademicRepository(pool);
    const sectionId = randomUUID();

    await pool.query(
      `
      INSERT INTO class_sections (
        id, section_code, term_id, course_id, lecturer_user_id, is_active
      )
      VALUES ($1, $2, $3, $4, $5, true)
      `,
      [sectionId, `ENR-${randomUUID().slice(0, 8)}`, SEED.term, SEED.course, SEED.lecturer],
    );

    expect(await isStudentEnrolled(pool.query.bind(pool), SEED.student, sectionId)).toBe(false);

    await repo.addEnrollment(SEED.student, sectionId);
    expect(await repo.isStudentEnrolled(SEED.student, sectionId)).toBe(true);

    await repo.removeEnrollment(SEED.student, sectionId);
    expect(await repo.isStudentEnrolled(SEED.student, sectionId)).toBe(false);
  });

  it("TC-FR-06-001: class section with schedule template generates Scheduled sessions", async () => {
    const token = await login(app, "academic-admin@attendly.local");
    const termCode = `S-${randomUUID().slice(0, 8)}`;

    const termRes = await app.inject({
      method: "POST",
      url: "/api/v1/terms",
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        code: termCode,
        name: "Session Gen Term",
        startDate: "2026-01-05",
        endDate: "2026-01-26",
        isActive: true,
      },
    });
    const termId = (termRes.json() as { data: { id: string } }).data.id;

    const sectionRes = await app.inject({
      method: "POST",
      url: "/api/v1/class-sections",
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        sectionCode: `SG-${randomUUID().slice(0, 8)}`,
        termId,
        courseId: SEED.course,
        lecturerUserId: SEED.lecturer,
        defaultRoomId: SEED.room,
        scheduleTemplate: {
          dayOfWeek: "Monday",
          startTime: "08:00",
          durationMinutes: 90,
        },
      },
    });

    expect(sectionRes.statusCode).toBe(200);
    const sectionBody = sectionRes.json() as {
      data: { id: string; generatedSessionCount: number };
    };
    expect(sectionBody.data.generatedSessionCount).toBeGreaterThan(0);

    const sessions = await pool.query(
      `
      SELECT state, room_id
      FROM class_sessions
      WHERE class_section_id = $1
      `,
      [sectionBody.data.id],
    );
    expect(sessions.rowCount).toBe(sectionBody.data.generatedSessionCount);
    for (const row of sessions.rows) {
      expect(row.state).toBe("Scheduled");
      expect(row.room_id).toBe(SEED.room);
    }
  });

  it("TC-FR-01-008: non-admin roles denied term management", async () => {
    const studentToken = await login(app, "student1@attendly.local");
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/terms",
      headers: {
        authorization: `Bearer ${studentToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        code: "X-2026",
        name: "Denied",
        startDate: "2026-08-01",
        endDate: "2026-12-31",
        isActive: true,
      },
    });
    expect(response.statusCode).toBe(403);
  });
});
