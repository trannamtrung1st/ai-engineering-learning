/**
 * Deterministic fixtures for REG-04/05/06 role-scope and export E2E scenarios.
 * Section A uses seed SE101-01 (lecturer-assigned); section B is unassigned.
 */
import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { expect } from "vitest";

const execFileAsync = promisify(execFile);
const REPO_ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../../../..");

export const TEST_PASSWORD = "attendly-test-password";

/** Role-matrix E2E seed — section A aligns with scripts/db-seed.mjs SE101-01. */
export const ROLE_MATRIX_SEED = {
  term: "20000000-0000-4000-8000-000000000001",
  course: "30000000-0000-4000-8000-000000000001",
  room: "40000000-0000-4000-8000-000000000001",
  sectionA: "50000000-0000-4000-8000-000000000001",
  sectionB: "50000000-0000-4000-8000-000000000078",
  lecturer: "60000000-0000-4000-8000-000000000001",
  student: "60000000-0000-4000-8000-000000000002",
  academicAdmin: "60000000-0000-4000-8000-000000000005",
  systemAuditor: "60000000-0000-4000-8000-000000000006",
  itAdmin: "60000000-0000-4000-8000-000000000088",
} as const;

export const ROLE_MATRIX_EMAILS = {
  lecturer: "lecturer@attendly.local",
  student: "student1@attendly.local",
  academicAdmin: "academic-admin@attendly.local",
  systemAuditor: "system-auditor@attendly.local",
  itAdmin: "e2e-itadmin@attendly.local",
} as const;

export async function ensureMigratedAndSeeded(): Promise<void> {
  const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
  await execFileAsync("node", ["scripts/db-migrate.mjs"], {
    cwd: REPO_ROOT,
    env: { ...process.env, DATABASE_URL: databaseUrl!, SEED_ENABLED: "true" },
  });
  await execFileAsync("node", ["scripts/db-seed.mjs"], {
    cwd: REPO_ROOT,
    env: { ...process.env, DATABASE_URL: databaseUrl!, SEED_ENABLED: "true" },
  });
}

export async function waitForSeededDb(client: pg.Client, attempts = 60): Promise<void> {
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
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 250));
  }
  throw new Error("Timed out waiting for migrated and seeded test database");
}

async function passwordHashFromSeed(pool: pg.Pool): Promise<string> {
  const result = await pool.query<{ password_hash: string }>(
    `SELECT password_hash FROM user_credentials WHERE user_id = $1 LIMIT 1`,
    [ROLE_MATRIX_SEED.lecturer],
  );
  const hash = result.rows[0]?.password_hash;
  if (!hash) throw new Error("Seed lecturer password hash missing");
  return hash;
}

export async function ensureRoleMatrixHierarchy(pool: pg.Pool): Promise<void> {
  await pool.query(
    `
    INSERT INTO class_sections (
      id, section_code, term_id, course_id, lecturer_user_id, default_room_id, capacity, is_active
    )
    VALUES ($1, 'E2E-B', $2, $3, $4, $5, 60, true)
    ON CONFLICT (id) DO NOTHING
    `,
    [
      ROLE_MATRIX_SEED.sectionB,
      ROLE_MATRIX_SEED.term,
      ROLE_MATRIX_SEED.course,
      ROLE_MATRIX_SEED.lecturer,
      ROLE_MATRIX_SEED.room,
    ],
  );

  const passwordHash = await passwordHashFromSeed(pool);
  await pool.query(
    `
    INSERT INTO users (id, email, display_name, is_active)
    VALUES ($1, $2, 'E2E IT Admin', true)
    ON CONFLICT (id) DO NOTHING
    `,
    [ROLE_MATRIX_SEED.itAdmin, ROLE_MATRIX_EMAILS.itAdmin],
  );
  await pool.query(
    `
    INSERT INTO user_credentials (user_id, password_hash)
    VALUES ($1, $2)
    ON CONFLICT (user_id) DO NOTHING
    `,
    [ROLE_MATRIX_SEED.itAdmin, passwordHash],
  );
  await pool.query(
    `
    INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
    VALUES ($1, $2, 'ITAdmin', 'Institution', NULL)
    ON CONFLICT (id) DO NOTHING
    `,
    ["90000000-0000-4000-8000-000000000088", ROLE_MATRIX_SEED.itAdmin],
  );
}

export async function login(app: FastifyInstance, email: string): Promise<string> {
  const response = await app.inject({
    method: "POST",
    url: "/api/v1/auth/login",
    payload: { email, password: TEST_PASSWORD },
  });
  expect(response.statusCode).toBe(200);
  return (response.json() as { data: { accessToken: string } }).data.accessToken;
}

export async function insertClosedSession(
  pool: pg.Pool,
  sectionId: string,
  startAt = "2026-05-10T08:00:00Z",
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
    [sessionId, sectionId, ROLE_MATRIX_SEED.room, start, end, ROLE_MATRIX_SEED.lecturer],
  );
  return sessionId;
}

export async function insertAttendanceRow(
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

export async function deleteExportJobsForActor(pool: pg.Pool, actorUserId: string): Promise<void> {
  await pool.query(`DELETE FROM audit_logs WHERE target_type = 'ExportJob' AND actor_user_id = $1`, [
    actorUserId,
  ]);
  await pool.query(`DELETE FROM export_jobs WHERE actor_user_id = $1`, [actorUserId]);
}

export function assertDenialWithoutLeakage(body: {
  data: unknown;
  meta?: { pagination?: { totalItems?: number; totalPages?: number } };
  error?: { code?: string; details?: unknown };
}): void {
  expect(body.data).toBeNull();
  expect(body.error?.code).toMatch(/Forbidden|OutOfScope|Unauthenticated/);
  if (body.meta?.pagination) {
    expect(body.meta.pagination.totalItems).toBeUndefined();
    expect(body.meta.pagination.totalPages).toBeUndefined();
  }
  if (body.error?.details && typeof body.error.details === "object") {
    const details = JSON.stringify(body.error.details);
    expect(details).not.toMatch(/studentCode|attendanceStatus|Present|Absent/);
  }
}

export async function completeExport(
  app: FastifyInstance,
  token: string,
  filters: { termId?: string; classSectionId?: string },
): Promise<{ exportJobId: string; csv: string }> {
  const exportResponse = await app.inject({
    method: "POST",
    url: "/api/v1/exports/attendance",
    headers: {
      authorization: `Bearer ${token}`,
      "idempotency-key": randomUUID(),
    },
    payload: { format: "csv", filters },
  });
  expect(exportResponse.statusCode).toBe(202);
  const exportBody = exportResponse.json() as { data: { exportJobId: string } };

  const downloadResponse = await app.inject({
    method: "GET",
    url: `/api/v1/exports/attendance/${exportBody.data.exportJobId}`,
    headers: { authorization: `Bearer ${token}`, accept: "text/csv" },
  });
  expect(downloadResponse.statusCode).toBe(200);
  return { exportJobId: exportBody.data.exportJobId, csv: downloadResponse.body };
}
