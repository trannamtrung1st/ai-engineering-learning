/**
 * Isolated fixtures for performance-smoke integration and e2e suites.
 * Traceability: AC-20 AC-21 AC-22 NFR-01 NFR-03 NFR-16
 */
import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { expect } from "vitest";
import { TEST_PASSWORD } from "./critical-path-fixtures.js";

export const PERF_STUDENTS_PER_SECTION = 20;
export const PERF_BURST_CONCURRENCY = 5;

/** Isolated hierarchy for performance smoke (class-start burst profile). */
export const PERF_SMOKE_SEED = {
  faculty: "10000000-0000-4000-8000-000000000090",
  term: "20000000-0000-4000-8000-000000000001",
  course: "30000000-0000-4000-8000-000000000090",
  sectionA: "50000000-0000-4000-8000-000000000090",
  sectionB: "50000000-0000-4000-8000-000000000091",
  room: "40000000-0000-4000-8000-000000000001",
  lecturer: "60000000-0000-4000-8000-000000000001",
  lecturerRoleA: "70000000-0000-4000-8000-000000000090",
  lecturerRoleB: "70000000-0000-4000-8000-000000000091",
  coursePolicy: "80000000-0000-4000-8000-000000000090",
  sectionPolicyA: "80000000-0000-4000-8000-000000000091",
  sectionPolicyB: "80000000-0000-4000-8000-000000000092",
} as const;

export const PERF_SMOKE_EMAILS = {
  lecturer: "lecturer@attendly.local",
  itAdmin: "e2e-itadmin@attendly.local",
} as const;

/** Preview/browser ITAdmin actor for NFR-16 PG-15 incident triage (TC-NFR-16-015). */
export const PERF_IT_ADMIN_SEED = {
  userId: "60000000-0000-4000-8000-000000000088",
  roleAssignmentId: "90000000-0000-4000-8000-000000000088",
} as const;

export function perfStudentId(sectionIndex: 0 | 1, studentIndex: number): string {
  const sectionOffset = sectionIndex === 0 ? 0 : PERF_STUDENTS_PER_SECTION;
  const ordinal = sectionOffset + studentIndex + 1;
  return `61000000-0000-4000-8000-${String(ordinal).padStart(12, "0")}`;
}

export function perfStudentEmail(sectionIndex: 0 | 1, studentIndex: number): string {
  const sectionOffset = sectionIndex === 0 ? 0 : PERF_STUDENTS_PER_SECTION;
  const ordinal = sectionOffset + studentIndex + 1;
  return `perf-student-${String(ordinal).padStart(2, "0")}@attendly.local`;
}

export function allPerfStudentIds(): string[] {
  const ids: string[] = [];
  for (let section = 0; section < 2; section += 1) {
    for (let i = 0; i < PERF_STUDENTS_PER_SECTION; i += 1) {
      ids.push(perfStudentId(section as 0 | 1, i));
    }
  }
  return ids;
}

export async function ensurePerformanceSmokeHierarchy(pool: pg.Pool): Promise<void> {
  await pool.query(
    `
    INSERT INTO faculties (id, code, name, is_active)
    VALUES ($1, 'PERF-FAC', 'Performance Smoke Faculty', true)
    ON CONFLICT (id) DO NOTHING
    `,
    [PERF_SMOKE_SEED.faculty],
  );

  await pool.query(
    `
    INSERT INTO courses (id, code, name, faculty_id, credit_units, is_active)
    VALUES ($1, 'PERF101', 'Performance Smoke Course', $2, 3, true)
    ON CONFLICT (id) DO NOTHING
    `,
    [PERF_SMOKE_SEED.course, PERF_SMOKE_SEED.faculty],
  );

  for (const [sectionId, code] of [
    [PERF_SMOKE_SEED.sectionA, "PERF-A"],
    [PERF_SMOKE_SEED.sectionB, "PERF-B"],
  ] as const) {
    await pool.query(
      `
      INSERT INTO class_sections (
        id, section_code, term_id, course_id, lecturer_user_id, default_room_id, capacity, is_active
      )
      VALUES ($1, $2, $3, $4, $5, $6, 60, true)
      ON CONFLICT (id) DO NOTHING
      `,
      [
        sectionId,
        code,
        PERF_SMOKE_SEED.term,
        PERF_SMOKE_SEED.course,
        PERF_SMOKE_SEED.lecturer,
        PERF_SMOKE_SEED.room,
      ],
    );
  }

  await pool.query(
    `
    INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
    VALUES ($1, $2, 'Lecturer', 'ClassSection', $3)
    ON CONFLICT (user_id, role, scope_type, scope_id) DO NOTHING
    `,
    [PERF_SMOKE_SEED.lecturerRoleA, PERF_SMOKE_SEED.lecturer, PERF_SMOKE_SEED.sectionA],
  );
  await pool.query(
    `
    INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
    VALUES ($1, $2, 'Lecturer', 'ClassSection', $3)
    ON CONFLICT (user_id, role, scope_type, scope_id) DO NOTHING
    `,
    [PERF_SMOKE_SEED.lecturerRoleB, PERF_SMOKE_SEED.lecturer, PERF_SMOKE_SEED.sectionB],
  );

  for (const sectionId of [PERF_SMOKE_SEED.sectionA, PERF_SMOKE_SEED.sectionB]) {
    await pool.query(`DELETE FROM attendance_policies WHERE scope_type = 'ClassSection' AND scope_id = $1`, [
      sectionId,
    ]);
  }
  await pool.query(`DELETE FROM attendance_policies WHERE scope_type = 'Course' AND scope_id = $1`, [
    PERF_SMOKE_SEED.course,
  ]);

  await pool.query(
    `
    INSERT INTO attendance_policies (
      id, scope_type, scope_id, present_window_minutes, late_window_minutes,
      manual_edit_window_hours, gps_required, gps_radius_meters, is_active, field_overrides
    )
    VALUES ($1, 'Course', $2, 15, 15, 24, false, 100, true, $3::jsonb)
    ON CONFLICT (id) DO UPDATE SET gps_required = false, is_active = true
    `,
    [
      PERF_SMOKE_SEED.coursePolicy,
      PERF_SMOKE_SEED.course,
      JSON.stringify({ gpsRequired: true, presentWindowMinutes: true, lateWindowMinutes: true }),
    ],
  );

  for (const [sectionId, policyId] of [
    [PERF_SMOKE_SEED.sectionA, PERF_SMOKE_SEED.sectionPolicyA],
    [PERF_SMOKE_SEED.sectionB, PERF_SMOKE_SEED.sectionPolicyB],
  ] as const) {
    await pool.query(
      `
      INSERT INTO attendance_policies (
        id, scope_type, scope_id, present_window_minutes, late_window_minutes,
        manual_edit_window_hours, gps_required, gps_radius_meters, is_active, field_overrides
      )
      VALUES ($1, 'ClassSection', $2, 15, 15, 24, false, 100, true, $3::jsonb)
      ON CONFLICT (id) DO UPDATE SET gps_required = false, is_active = true
      `,
      [
        policyId,
        sectionId,
        JSON.stringify({ gpsRequired: true, presentWindowMinutes: true, lateWindowMinutes: true }),
      ],
    );
  }

  const passwordSubquery = `(SELECT password_hash FROM user_credentials WHERE user_id = '60000000-0000-4000-8000-000000000002' LIMIT 1)`;

  for (let section = 0; section < 2; section += 1) {
    const sectionId = section === 0 ? PERF_SMOKE_SEED.sectionA : PERF_SMOKE_SEED.sectionB;
    for (let i = 0; i < PERF_STUDENTS_PER_SECTION; i += 1) {
      const studentId = perfStudentId(section as 0 | 1, i);
      const email = perfStudentEmail(section as 0 | 1, i);

      await pool.query(
        `
        INSERT INTO users (id, email, display_name, is_active)
        VALUES ($1, $2, $3, true)
        ON CONFLICT (id) DO NOTHING
        `,
        [studentId, email, `Perf Student ${section === 0 ? "A" : "B"}-${i + 1}`],
      );

      await pool.query(
        `
        INSERT INTO user_credentials (user_id, password_hash)
        VALUES ($1, ${passwordSubquery})
        ON CONFLICT (user_id) DO NOTHING
        `,
        [studentId],
      );

      await pool.query(
        `
        INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
        VALUES ($1, $2, 'Student', 'Self', $2)
        ON CONFLICT (user_id, role, scope_type, scope_id) DO NOTHING
        `,
        [randomUUID(), studentId],
      );

      await pool.query(
        `
        INSERT INTO student_profiles (user_id, student_code, faculty_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id) DO NOTHING
        `,
        [studentId, `PERF-${section === 0 ? "A" : "B"}-${String(i + 1).padStart(3, "0")}`, PERF_SMOKE_SEED.faculty],
      );

      await pool.query(
        `
        INSERT INTO enrollments (id, class_section_id, student_user_id, status)
        VALUES ($1, $2, $3, 'Active')
        ON CONFLICT (class_section_id, student_user_id) DO NOTHING
        `,
        [randomUUID(), sectionId, studentId],
      );
    }
  }
}

/** Ensures ITAdmin preview actor exists for PG-15 browser and integration smoke. */
export async function ensureItAdminPreviewActor(pool: pg.Pool): Promise<void> {
  const passwordSubquery = `(SELECT password_hash FROM user_credentials WHERE user_id = '60000000-0000-4000-8000-000000000002' LIMIT 1)`;

  await pool.query(
    `
    INSERT INTO users (id, email, display_name, is_active)
    VALUES ($1, $2, 'E2E IT Admin', true)
    ON CONFLICT (id) DO NOTHING
    `,
    [PERF_IT_ADMIN_SEED.userId, PERF_SMOKE_EMAILS.itAdmin],
  );

  await pool.query(
    `
    INSERT INTO user_credentials (user_id, password_hash)
    VALUES ($1, ${passwordSubquery})
    ON CONFLICT (user_id) DO NOTHING
    `,
    [PERF_IT_ADMIN_SEED.userId],
  );

  await pool.query(
    `
    INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
    VALUES ($1, $2, 'ITAdmin', 'Institution', NULL)
    ON CONFLICT (user_id, role, scope_type, scope_id) DO NOTHING
    `,
    [PERF_IT_ADMIN_SEED.roleAssignmentId, PERF_IT_ADMIN_SEED.userId],
  );
}

export async function loginPerf(app: FastifyInstance, email: string): Promise<string> {
  const response = await app.inject({
    method: "POST",
    url: "/api/v1/auth/login",
    payload: { email, password: TEST_PASSWORD },
  });
  expect(response.statusCode).toBe(200);
  return (response.json() as { data: { accessToken: string } }).data.accessToken;
}

export async function loginAllPerfStudents(app: FastifyInstance): Promise<Map<string, string>> {
  const tokens = new Map<string, string>();
  const emails: Array<{ studentId: string; email: string }> = [];
  for (let section = 0; section < 2; section += 1) {
    for (let i = 0; i < PERF_STUDENTS_PER_SECTION; i += 1) {
      emails.push({
        studentId: perfStudentId(section as 0 | 1, i),
        email: perfStudentEmail(section as 0 | 1, i),
      });
    }
  }

  for (let offset = 0; offset < emails.length; offset += PERF_BURST_CONCURRENCY) {
    const batch = emails.slice(offset, offset + PERF_BURST_CONCURRENCY);
    await Promise.all(
      batch.map(async ({ studentId, email }) => {
        tokens.set(studentId, await loginPerf(app, email));
      }),
    );
  }
  return tokens;
}

/** Run async tasks with bounded concurrency to avoid exhausting DB pools. */
export async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let nextIndex = 0;

  async function worker(): Promise<void> {
    while (nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await fn(items[index]!, index);
    }
  }

  const workers = Array.from({ length: Math.min(concurrency, items.length) }, () => worker());
  await Promise.all(workers);
  return results;
}

export async function insertPerfSession(
  pool: pg.Pool,
  sectionId: string,
  state: "Scheduled" | "Open" = "Scheduled",
): Promise<string> {
  const sessionId = randomUUID();
  const start = new Date();
  const end = new Date(start.getTime() + 90 * 60_000);

  if (state === "Open") {
    await pool.query(
      `
      INSERT INTO class_sessions (
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
        state, opened_at, opened_by_user_id
      )
      VALUES ($1, $2, $3, $4, $5, 'Open', $6, $7)
      `,
      [sessionId, sectionId, PERF_SMOKE_SEED.room, start, end, start, PERF_SMOKE_SEED.lecturer],
    );
  } else {
    await pool.query(
      `
      INSERT INTO class_sessions (
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at, state
      )
      VALUES ($1, $2, $3, $4, $5, 'Scheduled')
      `,
      [sessionId, sectionId, PERF_SMOKE_SEED.room, start, end],
    );
  }

  return sessionId;
}

export async function openPerfSession(
  app: FastifyInstance,
  sessionId: string,
  lecturerToken: string,
): Promise<{ qrPayload: string; openedAt: string }> {
  const response = await app.inject({
    method: "POST",
    url: `/api/v1/class-sessions/${sessionId}/open`,
    headers: {
      authorization: `Bearer ${lecturerToken}`,
      "idempotency-key": randomUUID(),
    },
    payload: {},
  });
  expect(response.statusCode).toBe(200);
  const body = response.json() as {
    data: { openedAt: string; qr: { qrPayload: string } };
  };
  return { qrPayload: body.data.qr.qrPayload, openedAt: body.data.openedAt };
}

export async function submitPerfCheckIn(
  app: FastifyInstance,
  options: {
    studentToken: string;
    qrToken: string;
    idempotencyKey?: string;
  },
) {
  return app.inject({
    method: "POST",
    url: "/api/v1/check-ins",
    headers: {
      authorization: `Bearer ${options.studentToken}`,
      "idempotency-key": options.idempotencyKey ?? randomUUID(),
    },
    payload: { qrToken: options.qrToken, clientTimestamp: new Date().toISOString() },
  });
}

export async function cleanupPerfSession(pool: pg.Pool, sessionId: string): Promise<void> {
  await pool.query(
    `DELETE FROM audit_logs WHERE target_id IN (
      SELECT id FROM attendance_records WHERE class_session_id = $1
    )`,
    [sessionId],
  );
  await pool.query(`DELETE FROM attendance_records WHERE class_session_id = $1`, [sessionId]);
  await pool.query(`DELETE FROM check_in_attempts WHERE class_session_id = $1`, [sessionId]);
  await pool.query(`DELETE FROM qr_session_tokens WHERE class_session_id = $1`, [sessionId]);
  await pool.query(`DELETE FROM audit_logs WHERE target_id = $1`, [sessionId]);
  await pool.query(`DELETE FROM class_sessions WHERE id = $1`, [sessionId]);
}

export async function countSuccessfulCheckIns(pool: pg.Pool, sessionId: string): Promise<number> {
  const result = await pool.query<{ count: number }>(
    `
    SELECT COUNT(*)::int AS count
    FROM attendance_records
    WHERE class_session_id = $1 AND status IN ('Present', 'Late')
    `,
    [sessionId],
  );
  return result.rows[0]?.count ?? 0;
}

export async function countEnrolledStudents(pool: pg.Pool, sectionId: string): Promise<number> {
  const result = await pool.query<{ count: number }>(
    `
    SELECT COUNT(*)::int AS count
    FROM enrollments
    WHERE class_section_id = $1 AND status = 'Active'
    `,
    [sectionId],
  );
  return result.rows[0]?.count ?? 0;
}
