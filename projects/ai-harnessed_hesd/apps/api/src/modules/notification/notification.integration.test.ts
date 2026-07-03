/**
 * Traceability: FR-26 BR-17
 * TC-FR-26-001 TC-FR-26-002 TC-FR-26-003 TC-FR-26-004 TC-FR-26-006 TC-FR-26-014
 * TC-BR-17-001 TC-BR-17-002 TC-BR-17-004 TC-BR-17-006 TC-BR-17-008 TC-BR-17-009 TC-BR-17-012 TC-BR-17-014
 */
import { randomUUID } from "node:crypto";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../../app.js";
import { createNotificationRepository } from "./repository.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const TEST_PASSWORD = "attendly-test-password";

const SEED = {
  faculty: "10000000-0000-4000-8000-000000000097",
  term: "20000000-0000-4000-8000-000000000097",
  course: "30000000-0000-4000-8000-000000000097",
  room: "40000000-0000-4000-8000-000000000001",
  section: "50000000-0000-4000-8000-000000000097",
  lecturer: "60000000-0000-4000-8000-000000000001",
  student: "60000000-0000-4000-8000-000000000002",
  academicAdmin: "60000000-0000-4000-8000-000000000005",
};

async function ensureM10TestHierarchy(pool: pg.Pool): Promise<void> {
  await pool.query(
    `
    INSERT INTO faculties (id, code, name, is_active)
    VALUES ($1, 'M10-FAC', 'Notification Test Faculty', true)
    ON CONFLICT (id) DO NOTHING
    `,
    [SEED.faculty],
  );
  await pool.query(
    `
    INSERT INTO terms (id, code, name, start_date, end_date, is_active)
    VALUES ($1, 'M10-TERM', 'Notification Test Term', '2026-01-01', '2026-06-30', true)
    ON CONFLICT (id) DO NOTHING
    `,
    [SEED.term],
  );
  await pool.query(
    `
    INSERT INTO courses (id, code, name, faculty_id, credit_units, is_active)
    VALUES ($1, 'M10-101', 'Notification Test Course', $2, 3, true)
    ON CONFLICT (id) DO NOTHING
    `,
    [SEED.course, SEED.faculty],
  );
  await pool.query(
    `
    INSERT INTO class_sections (
      id, section_code, term_id, course_id, lecturer_user_id, default_room_id, capacity, is_active
    )
    VALUES ($1, 'M10-SEC', $2, $3, $4, $5, 40, true)
    ON CONFLICT (id) DO NOTHING
    `,
    [SEED.section, SEED.term, SEED.course, SEED.lecturer, SEED.room],
  );
  await pool.query(
    `
    INSERT INTO enrollments (id, class_section_id, student_user_id, status)
    VALUES ($1, $2, $3, 'Active')
    ON CONFLICT (class_section_id, student_user_id) DO NOTHING
    `,
    [randomUUID(), SEED.section, SEED.student],
  );
  await pool.query(
    `
    INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
    VALUES ($1, $2, 'Lecturer', 'ClassSection', $3)
    ON CONFLICT (user_id, role, scope_type, scope_id) DO NOTHING
    `,
    [randomUUID(), SEED.lecturer, SEED.section],
  );
}

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

async function insertSectionPolicy(
  pool: pg.Pool,
  params: {
    absenceThresholdPercent: number;
    excusedCountsTowardThreshold?: boolean;
  },
): Promise<string> {
  const id = randomUUID();
  await pool.query(
    `
    INSERT INTO attendance_policies (
      id, scope_type, scope_id, present_window_minutes, late_window_minutes,
      manual_edit_window_hours, gps_required, gps_radius_meters,
      absence_threshold_percent, excused_counts_toward_threshold,
      is_active, field_overrides
    )
    VALUES ($1, 'ClassSection', $2, 15, 15, 24, false, 100, $3, $4, true, $5::jsonb)
    `,
    [
      id,
      SEED.section,
      params.absenceThresholdPercent,
      params.excusedCountsTowardThreshold ?? false,
      JSON.stringify({
        absenceThresholdPercent: true,
        excusedCountsTowardThreshold: true,
      }),
    ],
  );
  return id;
}

async function insertClosedSessionWithAttendance(
  pool: pg.Pool,
  status: "Absent" | "Present" | "Excused" | "Late" | "Manual Present",
): Promise<string> {
  const sessionId = randomUUID();
  const start = new Date();
  const end = new Date(start.getTime() + 90 * 60_000);

  await pool.query(
    `
    INSERT INTO class_sessions (
      id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
      state, opened_at, opened_by_user_id, closed_at, closed_by_user_id
    )
    VALUES ($1, $2, $3, $4, $5, 'Closed', $4, $6, $5, $6)
    `,
    [sessionId, SEED.section, SEED.room, start, end, SEED.lecturer],
  );

  await pool.query(
    `
    INSERT INTO attendance_records (
      id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
    )
    VALUES ($1, $2, $3, $4, $5, $6)
    `,
    [randomUUID(), sessionId, SEED.section, SEED.student, status, SEED.lecturer],
  );

  return sessionId;
}

async function insertOpenSession(pool: pg.Pool): Promise<string> {
  const sessionId = randomUUID();
  const start = new Date();
  const end = new Date(start.getTime() + 90 * 60_000);
  await pool.query(
    `
    INSERT INTO class_sessions (
      id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
      state, opened_at, opened_by_user_id
    )
    VALUES ($1, $2, $3, $4, $5, 'Open', $4, $6)
    `,
    [sessionId, SEED.section, SEED.room, start, end, SEED.lecturer],
  );
  return sessionId;
}

describe("M10 notification — FR-26 BR-17", () => {
  let app: FastifyInstance;
  let pool: pg.Pool;
  let repository: ReturnType<typeof createNotificationRepository>;
  const createdPolicyIds: string[] = [];
  const createdSessionIds: string[] = [];

  beforeAll(async () => {
    expect(databaseUrl).toBeTruthy();
    process.env.DATABASE_URL = databaseUrl;
    process.env.JWT_SECRET = "test-jwt";
    process.env.NOTIFICATION_MODULE_ENABLED = "true";

    const probe = new pg.Client({ connectionString: databaseUrl });
    await probe.connect();
    await waitForSeededDb(probe);
    await probe.end();

    app = await buildApp();
    await app.ready();
    pool = new pg.Pool({ connectionString: databaseUrl });
    repository = createNotificationRepository(pool);
    await ensureM10TestHierarchy(pool);
  });

  afterEach(async () => {
    for (const sessionId of createdSessionIds.splice(0)) {
      await pool.query(`DELETE FROM notification_delivery_queue WHERE alert_event_id IN (
        SELECT id FROM policy_alert_events WHERE class_section_id = $1
      )`, [SEED.section]);
      await pool.query(`DELETE FROM policy_alert_events WHERE class_section_id = $1`, [SEED.section]);
      await pool.query(`DELETE FROM audit_logs WHERE target_id = $1 OR correlation_id = $1`, [sessionId]);
      await pool.query(`DELETE FROM attendance_records WHERE class_session_id = $1`, [sessionId]);
      await pool.query(`DELETE FROM qr_session_tokens WHERE class_session_id = $1`, [sessionId]);
      await pool.query(`DELETE FROM class_sessions WHERE id = $1`, [sessionId]);
    }
    for (const policyId of createdPolicyIds.splice(0)) {
      await pool.query(`DELETE FROM attendance_policies WHERE id = $1`, [policyId]);
    }
    await pool.query(`DELETE FROM notification_delivery_queue WHERE alert_event_id IN (
      SELECT id FROM policy_alert_events WHERE class_section_id = $1
    )`, [SEED.section]);
    await pool.query(`DELETE FROM policy_alert_events WHERE class_section_id = $1`, [SEED.section]);
    await pool.query(`DELETE FROM audit_logs WHERE new_value->>'classSectionId' = $1`, [SEED.section]);
  });

  afterAll(async () => {
    await app?.close();
    await pool?.end().catch(() => undefined);
    delete process.env.NOTIFICATION_MODULE_ENABLED;
  });

  it("TC-FR-26-014 TC-BR-17-012: no alert at exactly 20%; alert after crossing above threshold", async () => {
    createdPolicyIds.push(await insertSectionPolicy(pool, { absenceThresholdPercent: 20 }));

    for (let i = 0; i < 10; i += 1) {
      createdSessionIds.push(await insertClosedSessionWithAttendance(pool, i < 2 ? "Absent" : "Present"));
    }

    let result = await repository.evaluateAbsenceThreshold(SEED.section, SEED.student);
    expect(result?.alertEmitted).toBe(false);
    expect(result?.snapshot.unexcusedAbsenceRate).toBe(20);

    createdSessionIds.push(await insertClosedSessionWithAttendance(pool, "Absent"));
    result = await repository.evaluateAbsenceThreshold(SEED.section, SEED.student);
    expect(result?.alertEmitted).toBe(true);
    expect(result?.snapshot.unexcusedAbsenceRate).toBeCloseTo(27.27, 1);

    const alerts = await pool.query(
      `SELECT 1 FROM policy_alert_events WHERE class_section_id = $1 AND student_user_id = $2`,
      [SEED.section, SEED.student],
    );
    expect(alerts.rowCount).toBe(1);
  });

  it("TC-FR-26-001 TC-BR-17-001 TC-FR-26-004: session close triggers absent finalization then threshold alert", async () => {
    createdPolicyIds.push(await insertSectionPolicy(pool, { absenceThresholdPercent: 20 }));

    for (let i = 0; i < 5; i += 1) {
      createdSessionIds.push(
        await insertClosedSessionWithAttendance(pool, i < 4 ? "Absent" : "Present"),
      );
    }

    const openSessionId = await insertOpenSession(pool);
    createdSessionIds.push(openSessionId);

    const lecturerToken = await login(app, "lecturer@attendly.local");
    const closeResponse = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${openSessionId}/close`,
      headers: {
        authorization: `Bearer ${lecturerToken}`,
        "idempotency-key": randomUUID(),
      },
    });
    expect(closeResponse.statusCode).toBe(200);

    const alerts = await pool.query(
      `SELECT unexcused_absence_rate, absence_threshold_percent FROM policy_alert_events
       WHERE class_section_id = $1 AND student_user_id = $2`,
      [SEED.section, SEED.student],
    );
    expect(alerts.rowCount).toBe(1);
    expect(Number(alerts.rows[0]!.unexcused_absence_rate)).toBeGreaterThan(20);

    const attendance = await pool.query(
      `SELECT status FROM attendance_records WHERE class_session_id = $1 AND student_user_id = $2`,
      [openSessionId, SEED.student],
    );
    expect(attendance.rows[0]?.status).toBe("Absent");
  });

  it("TC-FR-26-002 TC-BR-17-002: section threshold 20% wins over institution 30%", async () => {
    const institutionPolicyId = "80000000-0000-4000-8000-000000000001";
    await pool.query(
      `
      UPDATE attendance_policies
      SET absence_threshold_percent = 30,
          field_overrides = field_overrides || '{"absenceThresholdPercent": true}'::jsonb
      WHERE id = $1
      `,
      [institutionPolicyId],
    );
    createdPolicyIds.push(await insertSectionPolicy(pool, { absenceThresholdPercent: 20 }));

    for (let i = 0; i < 10; i += 1) {
      createdSessionIds.push(await insertClosedSessionWithAttendance(pool, i < 3 ? "Absent" : "Present"));
    }

    const result = await repository.evaluateAbsenceThreshold(SEED.section, SEED.student);
    expect(result?.alertEmitted).toBe(true);
    expect(result?.snapshot.unexcusedAbsenceRate).toBe(30);
    expect(result?.snapshot.absenceThresholdPercent).toBe(20);

    await pool.query(`DELETE FROM policy_alert_events WHERE class_section_id = $1`, [SEED.section]);

    await pool.query(`DELETE FROM attendance_policies WHERE scope_type = 'ClassSection' AND scope_id = $1`, [
      SEED.section,
    ]);
    createdPolicyIds.pop();

    const noSectionResult = await repository.evaluateAbsenceThreshold(SEED.section, SEED.student);
    expect(noSectionResult?.alertEmitted).toBe(false);
    expect(noSectionResult?.snapshot.absenceThresholdPercent).toBe(30);

    await pool.query(
      `
      UPDATE attendance_policies
      SET absence_threshold_percent = NULL,
          field_overrides = field_overrides - 'absenceThresholdPercent'
      WHERE id = $1
      `,
      [institutionPolicyId],
    );
  });

  it("TC-FR-26-006 TC-BR-17-006: close emits AbsenceThresholdAlert auditable via audit logs", async () => {
    createdPolicyIds.push(await insertSectionPolicy(pool, { absenceThresholdPercent: 20 }));

    for (let i = 0; i < 5; i += 1) {
      createdSessionIds.push(
        await insertClosedSessionWithAttendance(pool, i < 4 ? "Absent" : "Present"),
      );
    }

    const openSessionId = await insertOpenSession(pool);
    createdSessionIds.push(openSessionId);
    const lecturerToken = await login(app, "lecturer@attendly.local");

    const closeAt = new Date().toISOString();
    await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${openSessionId}/close`,
      headers: {
        authorization: `Bearer ${lecturerToken}`,
        "idempotency-key": randomUUID(),
      },
    });

    const adminToken = await login(app, "academic-admin@attendly.local");
    const auditResponse = await app.inject({
      method: "GET",
      url: `/api/v1/audit-logs?actionType=AbsenceThresholdAlert&targetId=${SEED.student}&from=${encodeURIComponent(closeAt)}`,
      headers: { authorization: `Bearer ${adminToken}` },
    });

    expect(auditResponse.statusCode).toBe(200);
    const auditBody = auditResponse.json() as {
      data: Array<{ actionType: string }>;
    };
    const alertRow = auditBody.data.find((row) => row.actionType === "AbsenceThresholdAlert");
    expect(alertRow).toBeTruthy();
  });

  it("TC-BR-17-008: scheduled batch evaluation emits alert without new session close", async () => {
    createdPolicyIds.push(await insertSectionPolicy(pool, { absenceThresholdPercent: 20 }));

    for (let i = 0; i < 5; i += 1) {
      createdSessionIds.push(await insertClosedSessionWithAttendance(pool, "Absent"));
    }

    const before = await pool.query(
      `SELECT status FROM attendance_records WHERE class_section_id = $1 AND student_user_id = $2`,
      [SEED.section, SEED.student],
    );

    await repository.evaluateAbsenceThresholdBatch(SEED.section);

    const after = await pool.query(
      `SELECT status FROM attendance_records WHERE class_section_id = $1 AND student_user_id = $2`,
      [SEED.section, SEED.student],
    );
    expect(after.rows).toEqual(before.rows);

    const alerts = await pool.query(
      `SELECT 1 FROM policy_alert_events WHERE class_section_id = $1 AND student_user_id = $2`,
      [SEED.section, SEED.student],
    );
    expect(alerts.rowCount).toBe(1);
  });

  it("TC-BR-17-009: deduplicates alerts while student remains above threshold", async () => {
    createdPolicyIds.push(await insertSectionPolicy(pool, { absenceThresholdPercent: 20 }));

    for (let i = 0; i < 3; i += 1) {
      createdSessionIds.push(await insertClosedSessionWithAttendance(pool, "Absent"));
    }

    const first = await repository.evaluateAbsenceThreshold(SEED.section, SEED.student);
    expect(first?.alertEmitted).toBe(true);

    createdSessionIds.push(await insertClosedSessionWithAttendance(pool, "Present"));
    const second = await repository.evaluateAbsenceThreshold(SEED.section, SEED.student);
    expect(second?.alertEmitted).toBe(false);

    const alerts = await pool.query(
      `SELECT COUNT(*)::text AS count FROM policy_alert_events WHERE class_section_id = $1 AND student_user_id = $2`,
      [SEED.section, SEED.student],
    );
    expect(Number(alerts.rows[0]?.count)).toBe(1);
  });

  it("TC-BR-17-014: alert emission does not mutate attendance records", async () => {
    createdPolicyIds.push(await insertSectionPolicy(pool, { absenceThresholdPercent: 20 }));
    createdSessionIds.push(await insertClosedSessionWithAttendance(pool, "Present"));
    createdSessionIds.push(await insertClosedSessionWithAttendance(pool, "Excused"));
    createdSessionIds.push(await insertClosedSessionWithAttendance(pool, "Absent"));
    createdSessionIds.push(await insertClosedSessionWithAttendance(pool, "Absent"));

    const before = await pool.query(
      `SELECT class_session_id, status, check_in_method FROM attendance_records
       WHERE class_section_id = $1 AND student_user_id = $2 ORDER BY class_session_id`,
      [SEED.section, SEED.student],
    );

    await repository.evaluateAbsenceThreshold(SEED.section, SEED.student);

    const after = await pool.query(
      `SELECT class_session_id, status, check_in_method FROM attendance_records
       WHERE class_section_id = $1 AND student_user_id = $2 ORDER BY class_session_id`,
      [SEED.section, SEED.student],
    );
    expect(after.rows).toEqual(before.rows);
  });
});
