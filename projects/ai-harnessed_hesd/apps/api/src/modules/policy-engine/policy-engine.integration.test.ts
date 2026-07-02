/**
 * Traceability: FR-24 FR-25 FR-35 BR-20 AC-09 AC-10
 * TC-FR-24-002 TC-FR-24-003 TC-FR-25-002 TC-FR-25-003 TC-BR-20-002 TC-BR-20-004 TC-BR-20-005
 * TC-AC-09-002 TC-AC-10-002 TC-FR-24-005 TC-FR-24-010
 */
import { randomUUID } from "node:crypto";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../../app.js";
import { createPolicyEngineRepository } from "./repository.js";
import { flattenResolvedPolicy } from "./resolver.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const TEST_PASSWORD = "attendly-test-password";

const SEED = {
  faculty: "10000000-0000-4000-8000-000000000001",
  course: "30000000-0000-4000-8000-000000000001",
  section: "50000000-0000-4000-8000-000000000001",
  policyFaculty: "10000000-0000-4000-8000-000000000099",
  policyCourse: "30000000-0000-4000-8000-000000000099",
  policySection: "50000000-0000-4000-8000-000000000099",
  room: "40000000-0000-4000-8000-000000000001",
  lecturer: "60000000-0000-4000-8000-000000000001",
  student: "60000000-0000-4000-8000-000000000002",
  academicAdmin: "60000000-0000-4000-8000-000000000005",
  institutionPolicy: "80000000-0000-4000-8000-000000000001",
  term: "20000000-0000-4000-8000-000000000001",
};

async function ensurePolicyTestHierarchy(pool: pg.Pool): Promise<void> {
  await pool.query(
    `
    INSERT INTO faculties (id, code, name, is_active)
    VALUES ($1, 'POL-FAC', 'Policy Test Faculty', true)
    ON CONFLICT (id) DO NOTHING
    `,
    [SEED.policyFaculty],
  );
  await pool.query(
    `
    INSERT INTO courses (id, code, name, faculty_id, credit_units, is_active)
    VALUES ($1, 'POL101', 'Policy Test Course', $2, 3, true)
    ON CONFLICT (id) DO NOTHING
    `,
    [SEED.policyCourse, SEED.policyFaculty],
  );
  await pool.query(
    `
    INSERT INTO class_sections (
      id, section_code, term_id, course_id, lecturer_user_id, default_room_id, capacity, is_active
    )
    VALUES ($1, 'POL-M06', $2, $3, $4, $5, 40, true)
    ON CONFLICT (id) DO NOTHING
    `,
    [SEED.policySection, SEED.term, SEED.policyCourse, SEED.lecturer, SEED.room],
  );
  await pool.query(
    `
    INSERT INTO enrollments (id, class_section_id, student_user_id, status)
    VALUES ($1, $2, $3, 'Active')
    ON CONFLICT (class_section_id, student_user_id) DO NOTHING
    `,
    [randomUUID(), SEED.policySection, SEED.student],
  );
  await pool.query(
    `
    INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
    VALUES ($1, $2, 'Lecturer', 'ClassSection', $3)
    ON CONFLICT (id) DO NOTHING
    `,
    ["70000000-0000-4000-8000-000000000099", SEED.lecturer, SEED.policySection],
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

async function insertOpenSessionWithQr(
  pool: pg.Pool,
  sectionId: string = SEED.policySection,
): Promise<{ sessionId: string; qrToken: string }> {
  const sessionId = randomUUID();
  const start = new Date();
  const end = new Date(start.getTime() + 90 * 60_000);
  await pool.query(
    `
    INSERT INTO class_sessions (
      id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
      state, opened_at, opened_by_user_id
    )
    VALUES ($1, $2, $3, $4, $5, 'Open', $6, $7)
    `,
    [sessionId, sectionId, SEED.room, start, end, start, SEED.lecturer],
  );

  const qrToken = randomUUID();
  const issuedAt = new Date();
  const expiresAt = new Date(issuedAt.getTime() + 30_000);
  await pool.query(
    `
    INSERT INTO qr_session_tokens (id, class_session_id, token_hash, state, issued_at, expires_at)
    VALUES ($1, $2, $3, 'Valid', $4, $5)
    `,
    [randomUUID(), sessionId, qrToken, issuedAt, expiresAt],
  );

  return { sessionId, qrToken };
}

async function insertPolicy(
  pool: pg.Pool,
  params: {
    scopeType: string;
    scopeId: string | null;
    presentWindowMinutes?: number;
    lateWindowMinutes?: number;
    manualEditWindowHours?: number;
    gpsRequired?: boolean;
    gpsRadiusMeters?: number | null;
    fieldOverrides: Record<string, boolean>;
  },
): Promise<string> {
  const id = randomUUID();
  await pool.query(
    `
    INSERT INTO attendance_policies (
      id, scope_type, scope_id, present_window_minutes, late_window_minutes,
      manual_edit_window_hours, gps_required, gps_radius_meters, is_active, field_overrides
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, true, $9::jsonb)
    `,
    [
      id,
      params.scopeType,
      params.scopeId,
      params.presentWindowMinutes ?? 15,
      params.lateWindowMinutes ?? 15,
      params.manualEditWindowHours ?? 24,
      params.gpsRequired ?? false,
      params.gpsRadiusMeters ?? 100,
      JSON.stringify(params.fieldOverrides),
    ],
  );
  return id;
}

describe("M06 policy engine — FR-24 FR-25 FR-35 BR-20 AC-09 AC-10", () => {
  let app: FastifyInstance;
  let pool: pg.Pool;
  let repository: ReturnType<typeof createPolicyEngineRepository>;
  const createdPolicyIds: string[] = [];
  const createdSessions: string[] = [];

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
    repository = createPolicyEngineRepository(pool);
    await ensurePolicyTestHierarchy(pool);
  });

  afterEach(async () => {
    for (const policyId of createdPolicyIds.splice(0)) {
      await pool.query(`DELETE FROM audit_logs WHERE target_id = $1`, [policyId]);
      await pool.query(`DELETE FROM attendance_policies WHERE id = $1`, [policyId]);
    }
    for (const sessionId of createdSessions.splice(0)) {
      await pool.query(`DELETE FROM check_in_attempts WHERE class_session_id = $1`, [sessionId]);
      await pool.query(`DELETE FROM attendance_records WHERE class_session_id = $1`, [sessionId]);
      await pool.query(`DELETE FROM qr_session_tokens WHERE class_session_id = $1`, [sessionId]);
      await pool.query(`DELETE FROM class_sessions WHERE id = $1`, [sessionId]);
    }
  });

  afterAll(async () => {
    await app?.close();
    await pool?.end().catch(() => undefined);
  });

  it("TC-FR-24-002 TC-FR-24-003: persists scoped policy and resolves effective values", async () => {
    const adminToken = await login(app, "academic-admin@attendly.local");

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/policies",
      headers: {
        authorization: `Bearer ${adminToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        scopeType: "ClassSection",
        scopeId: SEED.policySection,
        checkInOpeningOffsetMinutes: 5,
        presentWindowMinutes: 20,
        lateWindowMinutes: 15,
        autoCloseEnabled: true,
        absenceThresholdPercent: 20,
        excusedCountsTowardThreshold: false,
        manualEditWindowHours: 48,
        adminApprovalRequired: false,
        gpsRequired: true,
        gpsRadiusMeters: 100,
      },
    });

    expect(response.statusCode).toBe(200);
    const body = response.json() as { data: { id: string; presentWindowMinutes: number; gpsRequired: boolean } };
    createdPolicyIds.push(body.data.id);
    expect(body.data.presentWindowMinutes).toBe(20);
    expect(body.data.gpsRequired).toBe(true);

    const resolved = await repository.resolveEffectivePolicy(SEED.policySection);
    expect(resolved).not.toBeNull();
    const flat = flattenResolvedPolicy(resolved!);
    expect(flat.presentWindowMinutes).toBe(20);
    expect(flat.gpsRequired).toBe(true);
    expect(flat.gpsRadiusMeters).toBe(100);
  });

  it("TC-FR-25-002 TC-BR-20-002: merges per-field precedence across hierarchy", async () => {
    createdPolicyIds.push(
      await insertPolicy(pool, {
        scopeType: "Faculty",
        scopeId: SEED.policyFaculty,
        presentWindowMinutes: 12,
        fieldOverrides: { presentWindowMinutes: true },
      }),
    );
    createdPolicyIds.push(
      await insertPolicy(pool, {
        scopeType: "Course",
        scopeId: SEED.policyCourse,
        lateWindowMinutes: 18,
        gpsRequired: true,
        gpsRadiusMeters: 120,
        fieldOverrides: { lateWindowMinutes: true, gpsRequired: true, gpsRadiusMeters: true },
      }),
    );
    createdPolicyIds.push(
      await insertPolicy(pool, {
        scopeType: "ClassSection",
        scopeId: SEED.policySection,
        presentWindowMinutes: 20,
        fieldOverrides: { presentWindowMinutes: true },
      }),
    );

    const resolved = await repository.resolveEffectivePolicy(SEED.policySection);
    const flat = flattenResolvedPolicy(resolved!);
    expect(flat.presentWindowMinutes).toBe(20);
    expect(flat.lateWindowMinutes).toBe(18);
    expect(flat.gpsRequired).toBe(true);
    expect(flat.gpsRadiusMeters).toBe(120);
    expect(flat.manualEditWindowHours).toBe(24);
  });

  it("TC-BR-20-004: section manualEditWindowHours governs edit window resolution", async () => {
    const policyId = await insertPolicy(pool, {
      scopeType: "ClassSection",
      scopeId: SEED.policySection,
      manualEditWindowHours: 72,
      fieldOverrides: { manualEditWindowHours: true },
    });
    createdPolicyIds.push(policyId);

    const resolved = await repository.resolveEffectivePolicy(SEED.policySection);
    expect(flattenResolvedPolicy(resolved!).manualEditWindowHours).toBe(72);
  });

  it("TC-FR-24-005 TC-FR-24-011: POST /v1/policies authorized for AcademicAdmin and denied for Student", async () => {
    const adminToken = await login(app, "academic-admin@attendly.local");
    const studentToken = await login(app, "student1@attendly.local");

    const denied = await app.inject({
      method: "POST",
      url: "/api/v1/policies",
      headers: { authorization: `Bearer ${studentToken}`, "idempotency-key": randomUUID() },
      payload: {
        scopeType: "ClassSection",
        scopeId: SEED.policySection,
        presentWindowMinutes: 15,
        lateWindowMinutes: 15,
        manualEditWindowHours: 24,
        gpsRequired: false,
      },
    });
    expect(denied.statusCode).toBe(403);

    const allowed = await app.inject({
      method: "POST",
      url: "/api/v1/policies",
      headers: { authorization: `Bearer ${adminToken}`, "idempotency-key": randomUUID() },
      payload: {
        scopeType: "ClassSection",
        scopeId: SEED.policySection,
        presentWindowMinutes: 22,
        lateWindowMinutes: 15,
        manualEditWindowHours: 24,
        gpsRequired: false,
      },
    });
    expect(allowed.statusCode).toBe(200);
    createdPolicyIds.push((allowed.json() as { data: { id: string } }).data.id);
  });

  it("TC-FR-24-010 TC-AC-09-002: gpsRequired policy drives GpsRequired on check-in", async () => {
    const policyId = await insertPolicy(pool, {
      scopeType: "ClassSection",
      scopeId: SEED.policySection,
      gpsRequired: true,
      gpsRadiusMeters: 100,
      fieldOverrides: { gpsRequired: true, gpsRadiusMeters: true },
    });
    createdPolicyIds.push(policyId);

    const { sessionId, qrToken } = await insertOpenSessionWithQr(pool);
    createdSessions.push(sessionId);

    const studentToken = await login(app, "student1@attendly.local");
    const checkIn = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: {
        authorization: `Bearer ${studentToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        qrToken,
        clientTimestamp: new Date().toISOString(),
      },
    });

    expect(checkIn.statusCode).toBe(422);
    expect((checkIn.json() as { error: { code: string } }).error.code).toBe("GpsRequired");
  });

  it("TC-AC-10-002 TC-FR-35-003: out-of-radius GPS rejected without attendance write", async () => {
    const policyId = await insertPolicy(pool, {
      scopeType: "ClassSection",
      scopeId: SEED.policySection,
      gpsRequired: true,
      gpsRadiusMeters: 100,
      fieldOverrides: { gpsRequired: true, gpsRadiusMeters: true },
    });
    createdPolicyIds.push(policyId);

    const { sessionId, qrToken } = await insertOpenSessionWithQr(pool);
    createdSessions.push(sessionId);

    const beforeCount = await pool.query(
      `SELECT COUNT(*)::int AS count FROM attendance_records WHERE class_session_id = $1 AND student_user_id = $2`,
      [sessionId, SEED.student],
    );
    expect(beforeCount.rows[0]?.count).toBe(0);

    const studentToken = await login(app, "student1@attendly.local");
    const checkIn = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: {
        authorization: `Bearer ${studentToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: {
        qrToken,
        clientTimestamp: new Date().toISOString(),
        gps: { latitude: 10.76408, longitude: 106.660172, accuracyMeters: 24.5 },
      },
    });

    expect(checkIn.statusCode).toBe(422);
    expect((checkIn.json() as { error: { code: string } }).error.code).toBe("OutOfRadius");

    const attempt = await pool.query<{
      outcome: string;
      distance_from_room_meters: string | null;
      gps_validation_result: string | null;
    }>(
      `SELECT outcome, distance_from_room_meters, gps_validation_result
       FROM check_in_attempts WHERE class_session_id = $1 AND student_user_id = $2`,
      [sessionId, SEED.student],
    );
    expect(attempt.rows[0]?.outcome).toBe("OutOfRadius");
    expect(Number(attempt.rows[0]?.distance_from_room_meters)).toBeGreaterThan(100);
    expect(attempt.rows[0]?.gps_validation_result).toBe("Fail");

    const afterCount = await pool.query(
      `SELECT COUNT(*)::int AS count FROM attendance_records WHERE class_session_id = $1 AND student_user_id = $2`,
      [sessionId, SEED.student],
    );
    expect(afterCount.rows[0]?.count).toBe(0);
  });

  it("TC-BR-20-005: institution-only policy resolves when no child overrides exist", async () => {
    const resolved = await repository.resolveEffectivePolicy(SEED.policySection);
    expect(resolved).not.toBeNull();
    const flat = flattenResolvedPolicy(resolved!);
    expect(flat.presentWindowMinutes).toBe(15);
    expect(flat.lateWindowMinutes).toBe(15);
    expect(flat.gpsRequired).toBe(false);
    expect(resolved!.presentWindowMinutes.source).toBe("Institution");
    expect(resolved!.gpsRequired.source).toBe("Institution");
  });

  it("TC-FR-25-003 TC-BR-20-004: section manualEditWindowHours governs lecturer correction window", async () => {
    const policyId = await insertPolicy(pool, {
      scopeType: "ClassSection",
      scopeId: SEED.policySection,
      manualEditWindowHours: 72,
      fieldOverrides: { manualEditWindowHours: true },
    });
    createdPolicyIds.push(policyId);

    const closedAt = new Date(Date.now() - 48 * 60 * 60 * 1000);
    const sessionId = randomUUID();
    createdSessions.push(sessionId);
    await pool.query(
      `
      INSERT INTO class_sessions (
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
        state, opened_at, opened_by_user_id, closed_at, closed_by_user_id
      )
      VALUES ($1, $2, $3, $4, $5, 'Closed', $4, $6, $7, $6)
      `,
      [
        sessionId,
        SEED.policySection,
        SEED.room,
        closedAt,
        new Date(closedAt.getTime() + 90 * 60_000),
        SEED.lecturer,
        closedAt,
      ],
    );

    await pool.query(
      `
      INSERT INTO attendance_records (
        id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
      )
      VALUES ($1, $2, $3, $4, 'Absent', $5)
      `,
      [randomUUID(), sessionId, SEED.policySection, SEED.student, SEED.lecturer],
    );

    const lecturerToken = await login(app, "lecturer@attendly.local");
    const withinWindow = await app.inject({
      method: "PATCH",
      url: `/api/v1/class-sessions/${sessionId}/attendance/${SEED.student}`,
      headers: { authorization: `Bearer ${lecturerToken}`, "idempotency-key": randomUUID() },
      payload: { status: "Manual Present", reason: "Sinh vien co mat sau khi dong buoi." },
    });
    expect(withinWindow.statusCode).toBe(200);

    const expiredSessionId = randomUUID();
    createdSessions.push(expiredSessionId);
    const expiredClosedAt = new Date(Date.now() - 80 * 60 * 60 * 1000);
    await pool.query(
      `
      INSERT INTO class_sessions (
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at,
        state, opened_at, opened_by_user_id, closed_at, closed_by_user_id
      )
      VALUES ($1, $2, $3, $4, $5, 'Closed', $4, $6, $7, $6)
      `,
      [
        expiredSessionId,
        SEED.policySection,
        SEED.room,
        expiredClosedAt,
        new Date(expiredClosedAt.getTime() + 90 * 60_000),
        SEED.lecturer,
        expiredClosedAt,
      ],
    );
    await pool.query(
      `
      INSERT INTO attendance_records (
        id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
      )
      VALUES ($1, $2, $3, $4, 'Absent', $5)
      `,
      [randomUUID(), expiredSessionId, SEED.policySection, SEED.student, SEED.lecturer],
    );

    const outsideWindow = await app.inject({
      method: "PATCH",
      url: `/api/v1/class-sessions/${expiredSessionId}/attendance/${SEED.student}`,
      headers: { authorization: `Bearer ${lecturerToken}`, "idempotency-key": randomUUID() },
      payload: { status: "Manual Present", reason: "Late correction attempt." },
    });
    expect(outsideWindow.statusCode).toBe(409);
    expect((outsideWindow.json() as { error: { code: string } }).error.code).toBe("EditWindowExpired");
  });

  it("TC-FR-25-002: GET /policies/effective returns resolved values with per-field sources", async () => {
    createdPolicyIds.push(
      await insertPolicy(pool, {
        scopeType: "Course",
        scopeId: SEED.policyCourse,
        lateWindowMinutes: 18,
        gpsRequired: true,
        gpsRadiusMeters: 120,
        fieldOverrides: { lateWindowMinutes: true, gpsRequired: true, gpsRadiusMeters: true },
      }),
    );
    createdPolicyIds.push(
      await insertPolicy(pool, {
        scopeType: "ClassSection",
        scopeId: SEED.policySection,
        presentWindowMinutes: 20,
        fieldOverrides: { presentWindowMinutes: true },
      }),
    );

    const adminToken = await login(app, "academic-admin@attendly.local");
    const response = await app.inject({
      method: "GET",
      url: `/api/v1/policies/effective?classSectionId=${SEED.policySection}`,
      headers: { authorization: `Bearer ${adminToken}` },
    });

    expect(response.statusCode).toBe(200);
    const body = response.json() as {
      data: {
        values: { presentWindowMinutes: number; lateWindowMinutes: number; gpsRequired: boolean };
        sources: Record<string, string>;
      };
    };
    expect(body.data.values.presentWindowMinutes).toBe(20);
    expect(body.data.values.lateWindowMinutes).toBe(18);
    expect(body.data.values.gpsRequired).toBe(true);
    expect(body.data.sources.presentWindowMinutes).toBe("ClassSection");
    expect(body.data.sources.lateWindowMinutes).toBe("Course");
    expect(body.data.sources.gpsRequired).toBe("Course");
  });

  it("TC-FR-24-008: PATCH updates manual edit window and GPS settings with audit", async () => {
    const adminToken = await login(app, "academic-admin@attendly.local");
    const create = await app.inject({
      method: "POST",
      url: "/api/v1/policies",
      headers: { authorization: `Bearer ${adminToken}`, "idempotency-key": randomUUID() },
      payload: {
        scopeType: "ClassSection",
        scopeId: SEED.policySection,
        presentWindowMinutes: 15,
        lateWindowMinutes: 15,
        manualEditWindowHours: 24,
        gpsRequired: false,
      },
    });
    const policyId = (create.json() as { data: { id: string } }).data.id;
    createdPolicyIds.push(policyId);

    const patch = await app.inject({
      method: "PATCH",
      url: `/api/v1/policies/${policyId}`,
      headers: { authorization: `Bearer ${adminToken}`, "idempotency-key": randomUUID() },
      payload: { manualEditWindowHours: 72, gpsRequired: true, gpsRadiusMeters: 150 },
    });
    expect(patch.statusCode).toBe(200);
    const patched = (patch.json() as { data: { manualEditWindowHours: number; gpsRequired: boolean } }).data;
    expect(patched.manualEditWindowHours).toBe(72);
    expect(patched.gpsRequired).toBe(true);

    const audit = await pool.query(
      `SELECT 1 FROM audit_logs WHERE target_id = $1 AND action_type = 'PolicyChange'`,
      [policyId],
    );
    expect(audit.rowCount).toBeGreaterThan(0);
  });
});
