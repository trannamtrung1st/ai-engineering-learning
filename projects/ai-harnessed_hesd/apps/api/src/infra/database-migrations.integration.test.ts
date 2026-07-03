/**
 * Generated test-case traceability (integration/e2e layers for slice acceptance tags):
 * AC-05 AC-07 AC-08 BR-02 BR-06 BR-07 BR-08 BR-09 BR-10 BR-14 BR-16 BR-18 BR-19 BR-23
 * FR-04 FR-08 FR-15 FR-17 FR-18 FR-19 FR-20 FR-22 FR-27 FR-36
 * NFR-01 NFR-03 NFR-04 NFR-06 NFR-07
 */
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const execFileAsync = promisify(execFile);
const REPO_ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../../../..");

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;

const CORE_TABLES = [
  "users",
  "user_role_assignments",
  "student_profiles",
  "lecturer_profiles",
  "faculties",
  "terms",
  "courses",
  "rooms",
  "class_sections",
  "enrollments",
  "class_sessions",
  "qr_session_tokens",
  "check_in_attempts",
  "attendance_records",
  "attendance_policies",
  "policy_snapshots",
  "audit_logs",
];

const SEED_IDS = {
  term: "20000000-0000-4000-8000-000000000001",
  section: "50000000-0000-4000-8000-000000000001",
  sessionOpen: "70000000-0000-4000-8000-000000000002",
  studentUser: "60000000-0000-4000-8000-000000000002",
  lecturerUser: "60000000-0000-4000-8000-000000000001",
};

async function runScript(scriptName: string) {
  await execFileAsync("node", [`scripts/${scriptName}`], {
    cwd: REPO_ROOT,
    env: { ...process.env, DATABASE_URL: databaseUrl!, SEED_ENABLED: "true" },
  });
}

describe("database migrations and seed fixtures — FR-04 FR-18 BR-06 BR-07 NFR-07", () => {
  let client: pg.Client;

  beforeAll(async () => {
    expect(databaseUrl, "DATABASE_URL must be set by harness test stack").toBeTruthy();
    await runScript("db-migrate.mjs");
    await runScript("db-seed.mjs");
    client = new pg.Client({ connectionString: databaseUrl });
    await client.connect();
  });

  afterAll(async () => {
    await client?.end().catch(() => undefined);
  });

  it("records migration bookkeeping including baseline and initial schema", async () => {
    const result = await client.query<{ id: string }>(
      `
      SELECT id
      FROM _attendly_schema_migrations
      WHERE id IN ('infra-local-runtime-compose-baseline', '0001_initial_schema')
      ORDER BY id
      `,
    );
    expect(result.rowCount).toBe(2);
  });

  it("creates core identity, academic, session, attendance, policy, and audit tables", async () => {
    for (const tableName of CORE_TABLES) {
      const result = await client.query<{ regclass: string | null }>(
        "SELECT to_regclass($1) AS regclass",
        [`public.${tableName}`],
      );
      expect(result.rows[0]?.regclass, `missing table ${tableName}`).toBeTruthy();
    }
  });

  it("seeds term, course, section, role assignments, and session states for workflow tests", async () => {
    const term = await client.query("SELECT code, is_active FROM terms WHERE id = $1", [
      SEED_IDS.term,
    ]);
    expect(term.rowCount).toBe(1);
    expect(term.rows[0]?.is_active).toBe(true);

    const section = await client.query(
      "SELECT section_code FROM class_sections WHERE id = $1",
      [SEED_IDS.section],
    );
    expect(section.rowCount).toBe(1);

    const enrollments = await client.query(
      "SELECT COUNT(*)::int AS count FROM enrollments WHERE class_section_id = $1 AND status = 'Active'",
      [SEED_IDS.section],
    );
    expect(enrollments.rows[0]?.count).toBeGreaterThanOrEqual(3);

    const roles = await client.query(
      `
      SELECT role, COUNT(*)::int AS count
      FROM user_role_assignments
      GROUP BY role
      ORDER BY role
      `,
    );
    const roleMap = Object.fromEntries(roles.rows.map((row) => [row.role, row.count]));
    expect(roleMap.Lecturer).toBeGreaterThanOrEqual(1);
    expect(roleMap.Student).toBeGreaterThanOrEqual(3);
    expect(roleMap.AcademicAdmin).toBeGreaterThanOrEqual(1);

    const sessions = await client.query(
      `
      SELECT state, COUNT(*)::int AS count
      FROM class_sessions
      WHERE class_section_id = $1
      GROUP BY state
      `,
      [SEED_IDS.section],
    );
    const sessionStates = Object.fromEntries(
      sessions.rows.map((row) => [row.state, row.count]),
    );
    expect(sessionStates.Scheduled).toBeGreaterThanOrEqual(1);
    expect(sessionStates.Open).toBeGreaterThanOrEqual(1);
  });

  it("enforces BR-06 enrollment uniqueness per class section and student", async () => {
    await expect(
      client.query(
        `
        INSERT INTO enrollments (id, class_section_id, student_user_id, status)
        VALUES ($1, $2, $3, 'Active')
        `,
        [randomUUID(), SEED_IDS.section, SEED_IDS.studentUser],
      ),
    ).rejects.toMatchObject({ code: "23505" });
  });

  it("enforces BR-07 one attendance record per student per session via unique constraint", async () => {
    const attemptId = randomUUID();
    const firstRecordId = randomUUID();
    const secondRecordId = randomUUID();

    await client.query(
      `
      INSERT INTO check_in_attempts (
        id, class_session_id, student_user_id, outcome
      )
      VALUES ($1, $2, $3, 'Success')
      `,
      [attemptId, SEED_IDS.sessionOpen, SEED_IDS.studentUser],
    );

    await client.query(
      `
      INSERT INTO attendance_records (
        id,
        class_session_id,
        class_section_id,
        student_user_id,
        status,
        check_in_method,
        check_in_at,
        source_attempt_id
      )
      VALUES ($1, $2, $3, $4, 'Present', 'QR', now(), $5)
      `,
      [
        firstRecordId,
        SEED_IDS.sessionOpen,
        SEED_IDS.section,
        SEED_IDS.studentUser,
        attemptId,
      ],
    );

    await expect(
      client.query(
        `
        INSERT INTO attendance_records (
          id,
          class_session_id,
          class_section_id,
          student_user_id,
          status,
          check_in_method,
          check_in_at
        )
        VALUES ($1, $2, $3, $4, 'Late', 'QR', now())
        `,
        [
          secondRecordId,
          SEED_IDS.sessionOpen,
          SEED_IDS.section,
          SEED_IDS.studentUser,
        ],
      ),
    ).rejects.toMatchObject({ code: "23505" });

    const count = await client.query<{ count: number }>(
      `
      SELECT COUNT(*)::int AS count
      FROM attendance_records
      WHERE class_session_id = $1 AND student_user_id = $2
      `,
      [SEED_IDS.sessionOpen, SEED_IDS.studentUser],
    );
    expect(count.rows[0]?.count).toBe(1);
  });

  it("supports FR-04 enrollment persistence prerequisites with section FK integrity", async () => {
    const orphanSectionId = randomUUID();
    await expect(
      client.query(
        `
        INSERT INTO enrollments (id, class_section_id, student_user_id, status)
        VALUES ($1, $2, $3, 'Active')
        `,
        [randomUUID(), orphanSectionId, SEED_IDS.studentUser],
      ),
    ).rejects.toMatchObject({ code: "23503" });
  });
});
