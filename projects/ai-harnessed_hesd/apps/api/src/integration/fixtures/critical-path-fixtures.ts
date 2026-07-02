/**
 * Deterministic fixtures for REG-01/02/03 critical-path integration scenarios.
 * Uses a dedicated faculty/course/section hierarchy to avoid cross-suite pollution.
 */
import { createHash, randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { expect } from "vitest";
import { QR_TTL_MS } from "../../modules/check-in-and-qr-orchestrator/qr-service.js";

export const TEST_PASSWORD = "attendly-test-password";

/** Isolated hierarchy for critical-path integration tests (REG-01..03). */
export const CRITICAL_PATH_SEED = {
  faculty: "10000000-0000-4000-8000-000000000088",
  term: "20000000-0000-4000-8000-000000000001",
  course: "30000000-0000-4000-8000-000000000088",
  sectionA: "50000000-0000-4000-8000-000000000088",
  sectionB: "50000000-0000-4000-8000-000000000089",
  room: "40000000-0000-4000-8000-000000000001",
  lecturer: "60000000-0000-4000-8000-000000000001",
  student1: "60000000-0000-4000-8000-000000000002",
  student2: "60000000-0000-4000-8000-000000000003",
  student3: "60000000-0000-4000-8000-000000000004",
  unenrolledStudent: "60000000-0000-4000-8000-000000000099",
  lecturerRoleAssignment: "70000000-0000-4000-8000-000000000088",
} as const;

export const CRITICAL_PATH_EMAILS = {
  lecturer: "lecturer@attendly.local",
  student1: "student1@attendly.local",
  student2: "student2@attendly.local",
  student3: "student3@attendly.local",
  unenrolled: "unenrolled-critical@attendly.local",
} as const;

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
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Timed out waiting for migrated and seeded test database");
}

export async function ensureCriticalPathHierarchy(pool: pg.Pool): Promise<void> {
  await pool.query(
    `
    INSERT INTO faculties (id, code, name, is_active)
    VALUES ($1, 'CP-FAC', 'Critical Path Faculty', true)
    ON CONFLICT (id) DO NOTHING
    `,
    [CRITICAL_PATH_SEED.faculty],
  );

  await pool.query(
    `
    INSERT INTO courses (id, code, name, faculty_id, credit_units, is_active)
    VALUES ($1, 'CP101', 'Critical Path Course', $2, 3, true)
    ON CONFLICT (id) DO NOTHING
    `,
    [CRITICAL_PATH_SEED.course, CRITICAL_PATH_SEED.faculty],
  );

  for (const [sectionId, code] of [
    [CRITICAL_PATH_SEED.sectionA, "CP-REG-A"],
    [CRITICAL_PATH_SEED.sectionB, "CP-REG-B"],
  ] as const) {
    await pool.query(
      `
      INSERT INTO class_sections (
        id, section_code, term_id, course_id, lecturer_user_id, default_room_id, capacity, is_active
      )
      VALUES ($1, $2, $3, $4, $5, $6, 40, true)
      ON CONFLICT (id) DO NOTHING
      `,
      [
        sectionId,
        code,
        CRITICAL_PATH_SEED.term,
        CRITICAL_PATH_SEED.course,
        CRITICAL_PATH_SEED.lecturer,
        CRITICAL_PATH_SEED.room,
      ],
    );
  }

  await pool.query(
    `
    INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
    VALUES ($1, $2, 'Lecturer', 'ClassSection', $3)
    ON CONFLICT (user_id, role, scope_type, scope_id) DO NOTHING
    `,
    [
      CRITICAL_PATH_SEED.lecturerRoleAssignment,
      CRITICAL_PATH_SEED.lecturer,
      CRITICAL_PATH_SEED.sectionA,
    ],
  );

  await pool.query(
    `
    INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
    VALUES ($1, $2, 'Lecturer', 'ClassSection', $3)
    ON CONFLICT (user_id, role, scope_type, scope_id) DO NOTHING
    `,
    ["70000000-0000-4000-8000-000000000089", CRITICAL_PATH_SEED.lecturer, CRITICAL_PATH_SEED.sectionB],
  );

  for (const sectionId of [CRITICAL_PATH_SEED.sectionA, CRITICAL_PATH_SEED.sectionB]) {
    await pool.query(`DELETE FROM attendance_policies WHERE scope_type = 'ClassSection' AND scope_id = $1`, [
      sectionId,
    ]);
  }
  await pool.query(`DELETE FROM attendance_policies WHERE scope_type = 'Course' AND scope_id = $1`, [
    CRITICAL_PATH_SEED.course,
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
      "80000000-0000-4000-8000-000000000087",
      CRITICAL_PATH_SEED.course,
      JSON.stringify({ gpsRequired: true, presentWindowMinutes: true, lateWindowMinutes: true }),
    ],
  );

  for (const [sectionId, policyId] of [
    [CRITICAL_PATH_SEED.sectionA, "80000000-0000-4000-8000-000000000088"],
    [CRITICAL_PATH_SEED.sectionB, "80000000-0000-4000-8000-000000000089"],
  ] as const) {
    await pool.query(
      `
      INSERT INTO attendance_policies (
        id, scope_type, scope_id, present_window_minutes, late_window_minutes,
        manual_edit_window_hours, gps_required, gps_radius_meters, is_active, field_overrides
      )
      VALUES ($1, 'ClassSection', $2, 15, 15, 24, false, 100, true, $3::jsonb)
      ON CONFLICT (id) DO UPDATE SET
        gps_required = false,
        is_active = true,
        field_overrides = EXCLUDED.field_overrides
      `,
      [
        policyId,
        sectionId,
        JSON.stringify({ gpsRequired: true, presentWindowMinutes: true, lateWindowMinutes: true }),
      ],
    );
  }

  await pool.query(
    `
    INSERT INTO users (id, email, display_name, is_active)
    VALUES ($1, $2, 'Unenrolled Critical Student', true)
    ON CONFLICT (id) DO NOTHING
    `,
    [CRITICAL_PATH_SEED.unenrolledStudent, CRITICAL_PATH_EMAILS.unenrolled],
  );

  await pool.query(
    `
    INSERT INTO user_credentials (user_id, password_hash)
    VALUES ($1, (SELECT password_hash FROM user_credentials WHERE user_id = $2 LIMIT 1))
    ON CONFLICT (user_id) DO NOTHING
    `,
    [CRITICAL_PATH_SEED.unenrolledStudent, CRITICAL_PATH_SEED.student1],
  );

  await pool.query(
    `
    INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
    VALUES ($1, $2, 'Student', 'Self', $2)
    ON CONFLICT (user_id, role, scope_type, scope_id) DO NOTHING
    `,
    ["90000000-0000-4000-8000-000000000099", CRITICAL_PATH_SEED.unenrolledStudent],
  );

  await pool.query(
    `
    INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
    VALUES ($1, $2, 'Student', 'ClassSection', $3)
    ON CONFLICT (user_id, role, scope_type, scope_id) DO NOTHING
    `,
    [randomUUID(), CRITICAL_PATH_SEED.unenrolledStudent, CRITICAL_PATH_SEED.sectionB],
  );

  for (const studentId of [
    CRITICAL_PATH_SEED.student1,
    CRITICAL_PATH_SEED.student2,
    CRITICAL_PATH_SEED.student3,
  ]) {
    await pool.query(
      `
      INSERT INTO enrollments (id, class_section_id, student_user_id, status)
      VALUES ($1, $2, $3, 'Active')
      ON CONFLICT (class_section_id, student_user_id) DO NOTHING
      `,
      [randomUUID(), CRITICAL_PATH_SEED.sectionA, studentId],
    );
  }

  await pool.query(
    `
    INSERT INTO enrollments (id, class_section_id, student_user_id, status)
    VALUES ($1, $2, $3, 'Active')
    ON CONFLICT (class_section_id, student_user_id) DO NOTHING
    `,
    [randomUUID(), CRITICAL_PATH_SEED.sectionB, CRITICAL_PATH_SEED.student2],
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

export async function insertSession(
  pool: pg.Pool,
  state: "Scheduled" | "Open" | "Closed",
  sectionId: string = CRITICAL_PATH_SEED.sectionA,
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
      [sessionId, sectionId, CRITICAL_PATH_SEED.room, start, end, start, CRITICAL_PATH_SEED.lecturer],
    );
  } else if (state === "Closed") {
    await pool.query(
      `
      INSERT INTO class_sessions (
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
        state, opened_at, opened_by_user_id, closed_at, closed_by_user_id
      )
      VALUES ($1, $2, $3, $4, $5, 'Closed', $6, $7, $8, $7)
      `,
      [sessionId, sectionId, CRITICAL_PATH_SEED.room, start, end, start, CRITICAL_PATH_SEED.lecturer, end],
    );
  } else {
    await pool.query(
      `
      INSERT INTO class_sessions (
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at, state
      )
      VALUES ($1, $2, $3, $4, $5, 'Scheduled')
      `,
      [sessionId, sectionId, CRITICAL_PATH_SEED.room, start, end],
    );
  }

  return sessionId;
}

export async function openSession(
  app: FastifyInstance,
  sessionId: string,
  lecturerToken: string,
  idempotencyKey: string = randomUUID(),
): Promise<{ qrPayload: string; expiresAt: string }> {
  const response = await app.inject({
    method: "POST",
    url: `/api/v1/class-sessions/${sessionId}/open`,
    headers: {
      authorization: `Bearer ${lecturerToken}`,
      "idempotency-key": idempotencyKey,
    },
    payload: {},
  });
  expect(response.statusCode).toBe(200);
  return (response.json() as { data: { qr: { qrPayload: string; expiresAt: string } } }).data.qr;
}

export async function closeSession(
  app: FastifyInstance,
  sessionId: string,
  lecturerToken: string,
  idempotencyKey: string = randomUUID(),
) {
  const response = await app.inject({
    method: "POST",
    url: `/api/v1/class-sessions/${sessionId}/close`,
    headers: {
      authorization: `Bearer ${lecturerToken}`,
      "idempotency-key": idempotencyKey,
    },
  });
  return response;
}

export async function submitCheckIn(
  app: FastifyInstance,
  options: {
    studentToken: string;
    qrToken: string;
    idempotencyKey?: string;
    requestId?: string;
  },
) {
  return app.inject({
    method: "POST",
    url: "/api/v1/check-ins",
    headers: {
      authorization: `Bearer ${options.studentToken}`,
      "idempotency-key": options.idempotencyKey ?? randomUUID(),
      ...(options.requestId ? { "x-request-id": options.requestId } : {}),
    },
    payload: { qrToken: options.qrToken, clientTimestamp: new Date().toISOString() },
  });
}

export async function expireToken(pool: pg.Pool, sessionId: string, qrPayload: string): Promise<void> {
  const expiredAt = new Date(Date.now() - 60_000);
  const issuedAt = new Date(expiredAt.getTime() - QR_TTL_MS);
  const tokenHash = createHash("sha256").update(qrPayload).digest("hex");
  await pool.query(`DELETE FROM qr_session_tokens WHERE class_session_id = $1`, [sessionId]);
  await pool.query(
    `
    INSERT INTO qr_session_tokens (id, class_session_id, token_hash, state, issued_at, expires_at)
    VALUES ($1, $2, $3, 'Valid', $4, $5)
    `,
    [randomUUID(), sessionId, tokenHash, issuedAt.toISOString(), expiredAt.toISOString()],
  );
}

export async function cleanupSession(pool: pg.Pool, sessionId: string): Promise<void> {
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

export async function countAttendanceRecords(
  pool: pg.Pool,
  sessionId: string,
  studentUserId: string,
): Promise<number> {
  const result = await pool.query<{ count: number }>(
    `
    SELECT COUNT(*)::int AS count
    FROM attendance_records
    WHERE class_session_id = $1 AND student_user_id = $2
    `,
    [sessionId, studentUserId],
  );
  return result.rows[0]?.count ?? 0;
}

export async function listAttemptOutcomes(
  pool: pg.Pool,
  sessionId: string,
  studentUserId: string,
): Promise<string[]> {
  const result = await pool.query<{ outcome: string }>(
    `
    SELECT outcome
    FROM check_in_attempts
    WHERE class_session_id = $1 AND student_user_id = $2
    ORDER BY submitted_at
    `,
    [sessionId, studentUserId],
  );
  return result.rows.map((row) => row.outcome);
}
