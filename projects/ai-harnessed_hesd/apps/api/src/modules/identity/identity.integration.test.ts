/**
 * Traceability: FR-15 FR-31 FR-32 BR-19 BR-22 NFR-09 AC-15 AC-19
 * TC-FR-15-002 TC-NFR-09-002 TC-FR-32-002 TC-FR-32-003 TC-FR-32-010 TC-BR-19-002 TC-BR-19-017
 */
import { randomUUID } from "node:crypto";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { authorize } from "./authorize.js";
import { createIdentityRepository } from "./repository.js";
import type { ActorContext } from "./types.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;

const SEED = {
  sectionA: "50000000-0000-4000-8000-000000000001",
  lecturer: "60000000-0000-4000-8000-000000000001",
  student: "60000000-0000-4000-8000-000000000002",
  academicAdmin: "60000000-0000-4000-8000-000000000005",
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

describe("M01 identity module integration — FR-31 FR-32 BR-19 NFR-09", () => {
  let pool: pg.Pool;
  let repo: ReturnType<typeof createIdentityRepository>;

  beforeAll(async () => {
    expect(databaseUrl).toBeTruthy();
    const probe = new pg.Client({ connectionString: databaseUrl });
    await probe.connect();
    await waitForSeededDb(probe);
    await probe.end();
    pool = new pg.Pool({ connectionString: databaseUrl });
    repo = createIdentityRepository(pool);

    const deptAdminId = randomUUID();
    await pool.query(
      `INSERT INTO users (id, email, display_name, is_active) VALUES ($1, $2, $3, true) ON CONFLICT DO NOTHING`,
      [deptAdminId, "dept-admin@attendly.local", "Dept Admin"],
    );
    await pool.query(
      `
      INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
      VALUES ($1, $2, 'DepartmentAdmin', 'Faculty', $3)
      ON CONFLICT DO NOTHING
      `,
      [randomUUID(), deptAdminId, SEED.faculty],
    );
    await pool.query(
      `
      INSERT INTO user_credentials (user_id, password_hash)
      VALUES ($1, '$2b$10$1yMZjG/gIlHk/2kkZvMvt..ZRMavzIRAD9Rz9ipO7EHz87QF79Qpq')
      ON CONFLICT (user_id) DO NOTHING
      `,
      [deptAdminId],
    );

    const auditorId = randomUUID();
    await pool.query(
      `INSERT INTO users (id, email, display_name, is_active) VALUES ($1, $2, $3, true) ON CONFLICT DO NOTHING`,
      [auditorId, "auditor@attendly.local", "Auditor"],
    );
    await pool.query(
      `
      INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
      VALUES ($1, $2, 'SystemAuditor', 'Faculty', $3)
      ON CONFLICT DO NOTHING
      `,
      [randomUUID(), auditorId, SEED.faculty],
    );
  });

  afterAll(async () => {
    await pool?.end().catch(() => undefined);
  });

  async function actorFor(userId: string): Promise<ActorContext> {
    const actor = await repo.buildActorContext(userId);
    expect(actor).toBeTruthy();
    return actor!;
  }

  it("M01 authorize enforces deny-by-default for Student audit read (NFR-09 TC-NFR-09-002)", async () => {
    const student = await actorFor(SEED.student);
    const decision = authorize(student, "AuditLog", "read", {});
    expect(decision.allowed).toBe(false);
  });

  it("M01 scope guard rejects lecturer export for foreign section before data access (BR-19)", async () => {
    const lecturer = await actorFor(SEED.lecturer);
    const foreignSectionId = randomUUID();
    const bindings = await repo.resolveScopeBindings({ classSectionId: foreignSectionId });
    const lecturerSections = await repo.getLecturerClassSectionIds(lecturer.userId);

    const decision = authorize(
      lecturer,
      "ExportJob",
      "execute",
      { classSectionId: foreignSectionId },
      {
        ...bindings,
        lecturerClassSectionIds: lecturerSections,
        classSectionFacultyId: bindings.classSectionFacultyId,
      },
    );
    expect(decision.allowed).toBe(false);
    if (!decision.allowed) {
      expect(decision.code).toBe("OutOfScope");
    }
  });

  it("DepartmentAdmin faculty scope permits in-faculty section report read (FR-31)", async () => {
    const result = await pool.query<{ user_id: string }>(
      `SELECT user_id FROM user_role_assignments WHERE role = 'DepartmentAdmin' LIMIT 1`,
    );
    const deptAdmin = await actorFor(result.rows[0].user_id);
    const bindings = await repo.resolveScopeBindings({ classSectionId: SEED.sectionA });
    const decision = authorize(
      deptAdmin,
      "ReportView",
      "read",
      { classSectionId: SEED.sectionA },
      {
        classSectionFacultyId: bindings.classSectionFacultyId,
        classSectionIdsForFaculty: [SEED.sectionA],
      },
    );
    expect(decision).toEqual({ allowed: true });
  });

  it("SystemAuditor cannot mutate attendance (FR-32 PRM-05)", async () => {
    const result = await pool.query<{ user_id: string }>(
      `SELECT user_id FROM user_role_assignments WHERE role = 'SystemAuditor' LIMIT 1`,
    );
    const auditor = await actorFor(result.rows[0].user_id);
    const bindings = await repo.resolveScopeBindings({ classSessionId: SEED.sessionOpen });
    const decision = authorize(
      auditor,
      "AttendanceRecord",
      "update",
      { classSessionId: SEED.sessionOpen, classSectionId: bindings.sessionClassSectionId },
      { lecturerClassSectionIds: [] },
    );
    expect(decision.allowed).toBe(false);
    if (!decision.allowed) {
      expect(decision.code).toBe("Forbidden");
    }
  });
});
