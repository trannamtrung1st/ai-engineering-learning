/**
 * Traceability: FR-11 FR-12 FR-18 FR-22 FR-34 BR-03 BR-07 AC-02 AC-03 AC-08
 * TC-FR-11-002 TC-FR-11-004 TC-FR-11-008 TC-FR-11-012 TC-FR-18-001 TC-FR-18-002 TC-FR-22-001 TC-FR-22-002 TC-FR-22-004
 * TC-BR-03-001 TC-BR-03-002 TC-BR-03-003 TC-BR-07-001 TC-BR-07-002 TC-AC-02-002 TC-AC-02-004 TC-AC-08-001
 */
import { createHash, randomUUID } from "node:crypto";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../../app.js";
import { QR_TTL_MS } from "./qr-service.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const TEST_PASSWORD = "attendly-test-password";

const SEED = {
  section: "50000000-0000-4000-8000-000000000001",
  room: "40000000-0000-4000-8000-000000000001",
  lecturer: "60000000-0000-4000-8000-000000000001",
  student: "60000000-0000-4000-8000-000000000002",
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

async function insertSession(
  pool: pg.Pool,
  state: "Scheduled" | "Open" | "Closed",
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
      [sessionId, SEED.section, SEED.room, start, end, start, SEED.lecturer],
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
      [sessionId, SEED.section, SEED.room, start, end, start, SEED.lecturer, end],
    );
  } else {
    await pool.query(
      `
      INSERT INTO class_sessions (
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at, state
      )
      VALUES ($1, $2, $3, $4, $5, 'Scheduled')
      `,
      [sessionId, SEED.section, SEED.room, start, end],
    );
  }

  return sessionId;
}

async function openSession(app: FastifyInstance, sessionId: string, lecturerToken: string) {
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
  return (response.json() as { data: { qr: { qrPayload: string; expiresAt: string } } }).data.qr;
}

async function cleanupSession(pool: pg.Pool, sessionId: string) {
  await pool.query(`DELETE FROM attendance_records WHERE class_session_id = $1`, [sessionId]);
  await pool.query(`DELETE FROM check_in_attempts WHERE class_session_id = $1`, [sessionId]);
  await pool.query(`DELETE FROM qr_session_tokens WHERE class_session_id = $1`, [sessionId]);
  await pool.query(`DELETE FROM class_sessions WHERE id = $1`, [sessionId]);
}

describe("M04 check-in and QR orchestrator — FR-11 FR-18 FR-22 BR-03 BR-07 AC-02 AC-08", () => {
  let app: FastifyInstance;
  let pool: pg.Pool;
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
  });

  afterEach(async () => {
    for (const sessionId of createdSessions.splice(0)) {
      await cleanupSession(pool, sessionId);
    }
  });

  afterAll(async () => {
    await app?.close();
    await pool?.end().catch(() => undefined);
  });

  function track(sessionId: string): string {
    createdSessions.push(sessionId);
    return sessionId;
  }

  it("TC-FR-11-002 TC-AC-02-002: issueToken persists 30-second TTL QR row", async () => {
    const sessionId = track(await insertSession(pool, "Scheduled"));
    const lecturerToken = await login(app, "lecturer@attendly.local");
    const qr = await openSession(app, sessionId, lecturerToken);

    const rows = await pool.query<{
      issued_at: Date;
      expires_at: Date;
      state: string;
    }>(
      `
      SELECT issued_at, expires_at, state
      FROM qr_session_tokens
      WHERE class_session_id = $1 AND state = 'Valid'
      `,
      [sessionId],
    );
    expect(rows.rowCount).toBeGreaterThan(0);
    const row = rows.rows[0]!;
    expect(row.state).toBe("Valid");
    const ttlMs = row.expires_at.getTime() - row.issued_at.getTime();
    expect(ttlMs).toBe(QR_TTL_MS);

    const checkIn = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: {
        authorization: `Bearer ${await login(app, "student1@attendly.local")}`,
        "idempotency-key": randomUUID(),
      },
      payload: { qrToken: qr.qrPayload, clientTimestamp: new Date().toISOString() },
    });
    expect(checkIn.statusCode).toBe(200);
  });

  it("TC-FR-11-004 TC-AC-02-005: GET qr/current returns Valid token envelope", async () => {
    const sessionId = track(await insertSession(pool, "Scheduled"));
    const lecturerToken = await login(app, "lecturer@attendly.local");
    await openSession(app, sessionId, lecturerToken);

    const response = await app.inject({
      method: "GET",
      url: `/api/v1/class-sessions/${sessionId}/qr/current`,
      headers: { authorization: `Bearer ${lecturerToken}` },
    });

    expect(response.statusCode).toBe(200);
    const body = response.json() as {
      data: {
        classSessionId: string;
        tokenState: string;
        expiresAt: string;
        qrPayload: string;
      };
      error: null;
      meta: { requestId: string; timestamp: string };
    };
    expect(body.error).toBeNull();
    expect(body.data.classSessionId).toBe(sessionId);
    expect(body.data.tokenState).toBe("Valid");
    expect(body.data.qrPayload).toBeTruthy();
    expect(body.data.expiresAt).toBeTruthy();
    expect(body.meta.requestId).toBeTruthy();
  });

  it("TC-BR-03-001 TC-BR-03-002 TC-FR-22-003: ExpiredQr persists attempt without attendance", async () => {
    const sessionId = track(await insertSession(pool, "Scheduled"));
    const lecturerToken = await login(app, "lecturer@attendly.local");
    const qr = await openSession(app, sessionId, lecturerToken);
    const studentToken = await login(app, "student1@attendly.local");

    const expiredAt = new Date(Date.now() - 60_000);
    const issuedAt = new Date(expiredAt.getTime() - QR_TTL_MS);
    const tokenHash = createHash("sha256").update(qr.qrPayload).digest("hex");
    await pool.query(`DELETE FROM qr_session_tokens WHERE class_session_id = $1`, [sessionId]);
    await pool.query(
      `
      INSERT INTO qr_session_tokens (id, class_session_id, token_hash, state, issued_at, expires_at)
      VALUES ($1, $2, $3, 'Valid', $4, $5)
      `,
      [randomUUID(), sessionId, tokenHash, issuedAt.toISOString(), expiredAt.toISOString()],
    );

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: {
        authorization: `Bearer ${studentToken}`,
        "idempotency-key": randomUUID(),
        "x-request-id": randomUUID(),
      },
      payload: { qrToken: qr.qrPayload, clientTimestamp: new Date().toISOString() },
    });

    expect(response.statusCode).toBe(422);
    const body = response.json() as { error: { code: string } };
    expect(body.error.code).toBe("ExpiredQr");

    const attempts = await pool.query(
      `SELECT outcome FROM check_in_attempts WHERE class_session_id = $1 AND student_user_id = $2`,
      [sessionId, SEED.student],
    );
    expect(attempts.rows[0]?.outcome).toBe("ExpiredQr");

    const attendance = await pool.query(
      `SELECT id FROM attendance_records WHERE class_session_id = $1 AND student_user_id = $2`,
      [sessionId, SEED.student],
    );
    expect(attendance.rowCount).toBe(0);
  });

  it("TC-BR-03-003 TC-FR-22-005: multiple students share valid token within TTL", async () => {
    const sessionId = track(await insertSession(pool, "Scheduled"));
    const lecturerToken = await login(app, "lecturer@attendly.local");
    const qr = await openSession(app, sessionId, lecturerToken);

    for (const email of ["student1@attendly.local", "student2@attendly.local", "student3@attendly.local"]) {
      const response = await app.inject({
        method: "POST",
        url: "/api/v1/check-ins",
        headers: {
          authorization: `Bearer ${await login(app, email)}`,
          "idempotency-key": randomUUID(),
        },
        payload: { qrToken: qr.qrPayload, clientTimestamp: new Date().toISOString() },
      });
      expect(response.statusCode).toBe(200);
    }

    const records = await pool.query(
      `SELECT COUNT(*)::int AS count FROM attendance_records WHERE class_session_id = $1`,
      [sessionId],
    );
    expect(records.rows[0]?.count).toBe(3);
  });

  it("TC-FR-18-001 TC-BR-07-001 TC-AC-08-001: duplicate check-in returns 409 DuplicateCheckIn", async () => {
    const sessionId = track(await insertSession(pool, "Scheduled"));
    const lecturerToken = await login(app, "lecturer@attendly.local");
    const qr = await openSession(app, sessionId, lecturerToken);
    const studentToken = await login(app, "student1@attendly.local");

    const first = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: {
        authorization: `Bearer ${studentToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: { qrToken: qr.qrPayload, clientTimestamp: new Date().toISOString() },
    });
    expect(first.statusCode).toBe(200);

    const currentQr = await app.inject({
      method: "GET",
      url: `/api/v1/class-sessions/${sessionId}/qr/current`,
      headers: { authorization: `Bearer ${lecturerToken}` },
    });
    const freshToken = (currentQr.json() as { data: { qrPayload: string } }).data.qrPayload;

    const second = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: {
        authorization: `Bearer ${studentToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: { qrToken: freshToken, clientTimestamp: new Date().toISOString() },
    });
    expect(second.statusCode).toBe(409);
    expect((second.json() as { error: { code: string } }).error.code).toBe("DuplicateCheckIn");

    const records = await pool.query(
      `SELECT status, check_in_at FROM attendance_records WHERE class_session_id = $1 AND student_user_id = $2`,
      [sessionId, SEED.student],
    );
    expect(records.rowCount).toBe(1);

    const attempts = await pool.query(
      `SELECT outcome FROM check_in_attempts WHERE class_session_id = $1 AND student_user_id = $2 ORDER BY submitted_at`,
      [sessionId, SEED.student],
    );
    expect(attempts.rows.map((r) => r.outcome)).toEqual(["Success", "DuplicateCheckIn"]);
  });

  it("TC-FR-22-002: success attempt links attendance source_attempt_id", async () => {
    const sessionId = track(await insertSession(pool, "Scheduled"));
    const lecturerToken = await login(app, "lecturer@attendly.local");
    const qr = await openSession(app, sessionId, lecturerToken);
    const requestId = randomUUID();

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: {
        authorization: `Bearer ${await login(app, "student1@attendly.local")}`,
        "idempotency-key": randomUUID(),
        "x-request-id": requestId,
      },
      payload: { qrToken: qr.qrPayload, clientTimestamp: new Date().toISOString() },
    });
    expect(response.statusCode).toBe(200);

    const attempt = await pool.query<{ id: string; outcome: string; correlation_id: string }>(
      `SELECT id, outcome, correlation_id FROM check_in_attempts WHERE correlation_id = $1`,
      [requestId],
    );
    expect(attempt.rows[0]?.outcome).toBe("Success");

    const attendance = await pool.query<{ source_attempt_id: string; check_in_method: string }>(
      `
      SELECT source_attempt_id, check_in_method
      FROM attendance_records
      WHERE class_session_id = $1 AND student_user_id = $2
      `,
      [sessionId, SEED.student],
    );
    expect(attendance.rows[0]?.source_attempt_id).toBe(attempt.rows[0]?.id);
    expect(attendance.rows[0]?.check_in_method).toBe("QR");
  });

  it("TC-BR-03-006: Scheduled session yields SessionNotOpen before ExpiredQr", async () => {
    const sessionId = track(await insertSession(pool, "Scheduled"));
    const rawToken = randomUUID();
    const expiredAt = new Date(Date.now() - 60_000);
    await pool.query(
      `
      INSERT INTO qr_session_tokens (id, class_session_id, token_hash, state, issued_at, expires_at)
      VALUES ($1, $2, $3, 'Valid', $4, $5)
      `,
      [
        randomUUID(),
        sessionId,
        rawToken,
        new Date(expiredAt.getTime() - QR_TTL_MS).toISOString(),
        expiredAt.toISOString(),
      ],
    );

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: {
        authorization: `Bearer ${await login(app, "student1@attendly.local")}`,
        "idempotency-key": randomUUID(),
      },
      payload: { qrToken: rawToken, clientTimestamp: new Date().toISOString() },
    });
    expect(response.statusCode).toBe(422);
    expect((response.json() as { error: { code: string } }).error.code).toBe("SessionNotOpen");
  });
});
