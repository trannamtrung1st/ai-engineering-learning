/**
 * Traceability: FR-19 FR-14 AC-02 NFR-01 NFR-16
 * TC-FR-19-002 TC-FR-19-003 TC-FR-19-008 TC-FR-19-011 TC-FR-14-002 TC-FR-14-003 TC-FR-14-014 TC-AC-02-002 TC-NFR-16-003 TC-NFR-16-009
 */
import { randomUUID } from "node:crypto";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../../app.js";
import { QR_TTL_MS } from "../check-in-and-qr-orchestrator/qr-service.js";
import {
  getOperationalTelemetrySnapshot,
  realtimeDeliveryGateway,
  type RealtimeRosterEvent,
} from "./index.js";
import type { QrTokenIssuedTelemetry } from "./types.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const TEST_PASSWORD = "attendly-test-password";
type InjectResponse = Awaited<ReturnType<FastifyInstance["inject"]>>;

const SEED = {
  faculty: "10000000-0000-4000-8000-000000000098",
  term: "20000000-0000-4000-8000-000000000098",
  course: "30000000-0000-4000-8000-000000000098",
  room: "40000000-0000-4000-8000-000000000001",
  lecturer: "60000000-0000-4000-8000-000000000001",
  student: "60000000-0000-4000-8000-000000000002",
  student2: "60000000-0000-4000-8000-000000000003",
  student3: "60000000-0000-4000-8000-000000000004",
};

async function ensureM09TestHierarchy(pool: pg.Pool): Promise<void> {
  await pool.query(
    `
    INSERT INTO faculties (id, code, name, is_active)
    VALUES ($1, 'M09-FAC', 'Realtime Delivery Test Faculty', true)
    ON CONFLICT (id) DO NOTHING
    `,
    [SEED.faculty],
  );
  await pool.query(
    `
    INSERT INTO terms (id, code, name, start_date, end_date, is_active)
    VALUES ($1, 'M09-TERM', 'Realtime Delivery Test Term', '2026-01-01', '2026-06-30', true)
    ON CONFLICT (id) DO NOTHING
    `,
    [SEED.term],
  );
  await pool.query(
    `
    INSERT INTO courses (id, code, name, faculty_id, credit_units, is_active)
    VALUES ($1, 'M09-101', 'Realtime Delivery Test Course', $2, 3, true)
    ON CONFLICT (id) DO NOTHING
    `,
    [SEED.course, SEED.faculty],
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

async function insertSection(pool: pg.Pool): Promise<string> {
  const sectionId = randomUUID();
  await pool.query(
    `
    INSERT INTO class_sections (
      id, section_code, term_id, course_id, lecturer_user_id, default_room_id, capacity
    )
    VALUES ($1, $2, $3, $4, $5, $6, 50)
    `,
    [
      sectionId,
      `M09-${sectionId.slice(0, 8)}`,
      SEED.term,
      SEED.course,
      SEED.lecturer,
      SEED.room,
    ],
  );
  await pool.query(
    `
    INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
    VALUES ($1, $2, 'Lecturer', 'ClassSection', $3)
    ON CONFLICT (user_id, role, scope_type, scope_id) DO NOTHING
    `,
    [randomUUID(), SEED.lecturer, sectionId],
  );
  for (const studentId of [SEED.student, SEED.student2, SEED.student3]) {
    await pool.query(
      `
      INSERT INTO enrollments (id, class_section_id, student_user_id, status)
      VALUES ($1, $2, $3, 'Active')
      `,
      [randomUUID(), sectionId, studentId],
    );
  }
  return sectionId;
}

async function insertSession(pool: pg.Pool): Promise<{ sectionId: string; sessionId: string }> {
  const sectionId = await insertSection(pool);
  const sessionId = randomUUID();
  const start = new Date();
  const end = new Date(start.getTime() + 90 * 60_000);
  await pool.query(
    `
    INSERT INTO class_sessions (
      id, class_section_id, room_id, scheduled_start_at, scheduled_end_at, state
    )
    VALUES ($1, $2, $3, $4, $5, 'Scheduled')
    `,
    [sessionId, sectionId, SEED.room, start, end],
  );
  return { sectionId, sessionId };
}

async function cleanupFixture(pool: pg.Pool, fixture: { sectionId: string; sessionId: string }) {
  await pool.query(
    `
    DELETE FROM audit_logs
    WHERE target_id = $1
       OR target_id IN (SELECT id FROM attendance_records WHERE class_session_id = $1)
       OR target_id IN (SELECT id FROM check_in_attempts WHERE class_session_id = $1)
    `,
    [fixture.sessionId],
  );
  await pool.query(`DELETE FROM attendance_records WHERE class_session_id = $1`, [fixture.sessionId]);
  await pool.query(`DELETE FROM check_in_attempts WHERE class_session_id = $1`, [fixture.sessionId]);
  await pool.query(`DELETE FROM qr_session_tokens WHERE class_session_id = $1`, [fixture.sessionId]);
  await pool.query(`DELETE FROM class_sessions WHERE id = $1`, [fixture.sessionId]);
  await pool.query(
    `DELETE FROM user_role_assignments WHERE role = 'Lecturer' AND scope_type = 'ClassSection' AND scope_id = $1`,
    [fixture.sectionId],
  );
  await pool.query(`DELETE FROM enrollments WHERE class_section_id = $1`, [fixture.sectionId]);
  await pool.query(`DELETE FROM class_sections WHERE id = $1`, [fixture.sectionId]);
}

async function openSession(
  app: FastifyInstance,
  sessionId: string,
  lecturerToken: string,
): Promise<{ qrPayload: string; expiresAt: string }> {
  const response = await app.inject({
    method: "POST",
    url: `/api/v1/class-sessions/${sessionId}/open`,
    headers: {
      authorization: `Bearer ${lecturerToken}`,
      "idempotency-key": randomUUID(),
      "x-request-id": randomUUID(),
    },
  });
  expect(response.statusCode).toBe(200);
  return (response.json() as { data: { qr: { qrPayload: string; expiresAt: string } } }).data.qr;
}

function nextRosterEvent(sessionId: string): Promise<RealtimeRosterEvent> {
  return new Promise((resolve, reject) => {
    let unsubscribe = () => undefined;
    const timeout = setTimeout(() => {
      unsubscribe();
      reject(new Error(`Timed out waiting for roster event for ${sessionId}`));
    }, 2_000);
    unsubscribe = realtimeDeliveryGateway.subscribeToRoster(sessionId, (event) => {
      clearTimeout(timeout);
      unsubscribe();
      resolve(event);
    });
  });
}

async function captureRosterEvent(
  sessionId: string,
  action: () => Promise<InjectResponse>,
): Promise<{ event: RealtimeRosterEvent; response: InjectResponse }> {
  const eventPromise = nextRosterEvent(sessionId);
  const response = await action();
  const event = await eventPromise;
  return { event, response };
}

describe("M09 realtime delivery — FR-19 FR-14 AC-02 NFR-16", () => {
  let app: FastifyInstance;
  let pool: pg.Pool;
  const createdFixtures: Array<{ sectionId: string; sessionId: string }> = [];

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
    await ensureM09TestHierarchy(pool);
  });

  afterEach(async () => {
    realtimeDeliveryGateway.clearForTests();
    for (const fixture of createdFixtures.splice(0)) {
      await cleanupFixture(pool, fixture);
    }
  });

  afterAll(async () => {
    await app?.close();
    await pool?.end().catch(() => undefined);
  });

  async function createFixture(): Promise<{ sectionId: string; sessionId: string }> {
    const fixture = await insertSession(pool);
    createdFixtures.push(fixture);
    return fixture;
  }

  it("publishes committed check-in and duplicate rejection updates with polling-compatible roster data", async () => {
    const { sessionId } = await createFixture();
    const lecturerToken = await login(app, "lecturer@attendly.local");
    const studentToken = await login(app, "student1@attendly.local");
    const qr = await openSession(app, sessionId, lecturerToken);
    realtimeDeliveryGateway.clearForTests();

    const { event: successEvent, response: successResponse } = await captureRosterEvent(
      sessionId,
      () =>
        app.inject({
          method: "POST",
          url: "/api/v1/check-ins",
          headers: {
            authorization: `Bearer ${studentToken}`,
            "idempotency-key": randomUUID(),
            "x-request-id": randomUUID(),
          },
          payload: { qrToken: qr.qrPayload, clientTimestamp: new Date().toISOString() },
        }),
    );

    expect(successResponse.statusCode).toBe(200);
    expect(successEvent.reason).toBe("CheckInRecorded");
    expect(successEvent.roster.counts.present + successEvent.roster.counts.late).toBe(1);
    const successRow = successEvent.roster.rows.find((row) => row.studentUserId === SEED.student);
    expect(successRow?.latestAttemptOutcome).toBe("Success");

    const { event: duplicateEvent, response: duplicateResponse } = await captureRosterEvent(
      sessionId,
      () =>
        app.inject({
          method: "POST",
          url: "/api/v1/check-ins",
          headers: {
            authorization: `Bearer ${studentToken}`,
            "idempotency-key": randomUUID(),
            "x-request-id": randomUUID(),
          },
          payload: { qrToken: qr.qrPayload, clientTimestamp: new Date().toISOString() },
        }),
    );

    expect(duplicateResponse.statusCode).toBe(409);
    expect(duplicateEvent.roster.counts.rejectedAttempts).toBe(1);
    const duplicateRow = duplicateEvent.roster.rows.find((row) => row.studentUserId === SEED.student);
    expect(duplicateRow?.latestAttemptOutcome).toBe("DuplicateCheckIn");
    expect(duplicateRow?.attendanceStatus === "Present" || duplicateRow?.attendanceStatus === "Late").toBe(
      true,
    );

    const polling = await app.inject({
      method: "GET",
      url: `/api/v1/class-sessions/${sessionId}/attendance`,
      headers: { authorization: `Bearer ${lecturerToken}` },
    });
    expect(polling.statusCode).toBe(200);
    expect((polling.json() as { data: RealtimeRosterEvent["roster"] }).data).toEqual(duplicateEvent.roster);
  });

  it("publishes manual correction updates after attendance ledger commit", async () => {
    const { sessionId } = await createFixture();
    const lecturerToken = await login(app, "lecturer@attendly.local");
    await openSession(app, sessionId, lecturerToken);
    realtimeDeliveryGateway.clearForTests();

    const { event, response } = await captureRosterEvent(sessionId, () =>
      app.inject({
        method: "PATCH",
        url: `/api/v1/class-sessions/${sessionId}/attendance/${SEED.student2}`,
        headers: {
          authorization: `Bearer ${lecturerToken}`,
          "idempotency-key": randomUUID(),
          "x-request-id": randomUUID(),
        },
        payload: {
          status: "Manual Present",
          reason: "Sinh vien co mat nhung thiet bi khong quet duoc QR.",
        },
      }),
    );

    expect(response.statusCode).toBe(200);
    expect(event.reason).toBe("AttendanceCorrected");
    const corrected = event.roster.rows.find((row) => row.studentUserId === SEED.student2);
    expect(corrected?.attendanceStatus).toBe("Manual Present");
    expect(event.roster.counts.manualPresent).toBe(1);
  });

  it("records QR rotation health telemetry with 30-second token metadata", async () => {
    const { sessionId } = await createFixture();
    const lecturerToken = await login(app, "lecturer@attendly.local");
    await openSession(app, sessionId, lecturerToken);
    realtimeDeliveryGateway.clearForTests();

    const first = await app.inject({
      method: "GET",
      url: `/api/v1/class-sessions/${sessionId}/qr/current`,
      headers: { authorization: `Bearer ${lecturerToken}` },
    });
    expect(first.statusCode).toBe(200);

    await pool.query(
      `UPDATE qr_session_tokens SET state = 'Expired' WHERE class_session_id = $1`,
      [sessionId],
    );

    const second = await app.inject({
      method: "GET",
      url: `/api/v1/class-sessions/${sessionId}/qr/current`,
      headers: { authorization: `Bearer ${lecturerToken}` },
    });
    expect(second.statusCode).toBe(200);

    const telemetry = getOperationalTelemetrySnapshot({
      classSessionId: sessionId,
      type: "QrTokenIssued",
    }) as QrTokenIssuedTelemetry[];
    expect(telemetry).toHaveLength(2);
    for (const event of telemetry) {
      expect(event.type).toBe("QrTokenIssued");
      expect(event.ttlMs).toBe(QR_TTL_MS);
      expect(new Date(event.expiresAt).getTime() - new Date(event.issuedAt).getTime()).toBe(
        QR_TTL_MS,
      );
      expect(event.success).toBe(true);
    }
  });

  it("emits session close update with finalized absent rows", async () => {
    const { sessionId } = await createFixture();
    const lecturerToken = await login(app, "lecturer@attendly.local");
    await openSession(app, sessionId, lecturerToken);
    realtimeDeliveryGateway.clearForTests();

    const { event, response } = await captureRosterEvent(sessionId, () =>
      app.inject({
        method: "POST",
        url: `/api/v1/class-sessions/${sessionId}/close`,
        headers: {
          authorization: `Bearer ${lecturerToken}`,
          "idempotency-key": randomUUID(),
          "x-request-id": randomUUID(),
        },
      }),
    );

    expect(response.statusCode).toBe(200);
    expect(event.reason).toBe("SessionClosed");
    expect(event.roster.state).toBe("Closed");
    expect(event.roster.counts.pending).toBe(0);
    expect(event.roster.counts.absent).toBeGreaterThan(0);
  });
});
