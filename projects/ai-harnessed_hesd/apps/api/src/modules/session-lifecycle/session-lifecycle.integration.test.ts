/**
 * Traceability: FR-07 FR-08 BR-01 BR-02 BR-13 BR-21 AC-01 AC-05 AC-12
 * TC-FR-07-003 TC-FR-07-004 TC-FR-07-005 TC-FR-07-009 TC-FR-08-003 TC-FR-08-004 TC-FR-08-005 TC-FR-08-008
 * TC-BR-02-003 TC-BR-02-011 TC-AC-01-002 TC-AC-01-003 TC-AC-01-005 TC-AC-05-001 TC-AC-05-002 TC-AC-05-003
 */
import { randomUUID } from "node:crypto";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../../app.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const TEST_PASSWORD = "attendly-test-password";

const SEED = {
  section: "50000000-0000-4000-8000-000000000001",
  room: "40000000-0000-4000-8000-000000000001",
  lecturer: "60000000-0000-4000-8000-000000000001",
  student: "60000000-0000-4000-8000-000000000002",
  academicAdmin: "60000000-0000-4000-8000-000000000005",
  sessionScheduled: "70000000-0000-4000-8000-000000000001",
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
  state: "Scheduled" | "Open" | "Closed" | "Cancelled",
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
      VALUES ($1, $2, $3, $4, $5, $6)
      `,
      [sessionId, SEED.section, SEED.room, start, end, state],
    );
  }

  return sessionId;
}

describe("M03 session lifecycle — FR-07 FR-08 BR-01 BR-02 AC-01 AC-05", () => {
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

  afterEach(async () => {
    await pool.query(
      `UPDATE class_sessions SET state = 'Scheduled', opened_at = NULL, opened_by_user_id = NULL, closed_at = NULL, closed_by_user_id = NULL WHERE id = $1`,
      [SEED.sessionScheduled],
    );
    await pool.query(`DELETE FROM qr_session_tokens WHERE class_session_id = $1`, [
      SEED.sessionScheduled,
    ]);
    await pool.query(`DELETE FROM attendance_records WHERE class_session_id = $1`, [
      SEED.sessionScheduled,
    ]);
    await pool.query(`DELETE FROM audit_logs WHERE target_id = $1`, [SEED.sessionScheduled]);
  });

  afterAll(async () => {
    await app?.close();
    await pool?.end().catch(() => undefined);
  });

  it("TC-FR-07-003 TC-FR-07-004 TC-AC-01-005: open persists Open state with openedAt, actor, and QR token", async () => {
    const token = await login(app, "lecturer@attendly.local");

    const response = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${SEED.sessionScheduled}/open`,
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
      payload: {},
    });

    expect(response.statusCode).toBe(200);
    const body = response.json() as {
      data: {
        classSessionId: string;
        state: string;
        openedAt: string;
        qr: { expiresAt: string; qrPayload: string };
      };
      error: null;
      meta: { requestId: string; timestamp: string };
    };
    expect(body.error).toBeNull();
    expect(body.data.state).toBe("Open");
    expect(body.data.classSessionId).toBe(SEED.sessionScheduled);
    expect(body.data.openedAt).toBeTruthy();
    expect(body.data.qr.expiresAt).toBeTruthy();
    expect(body.data.qr.qrPayload).toBeTruthy();
    expect(body.meta.requestId).toBeTruthy();

    const dbSession = await pool.query(
      `SELECT state, opened_at, opened_by_user_id FROM class_sessions WHERE id = $1`,
      [SEED.sessionScheduled],
    );
    expect(dbSession.rows[0]?.state).toBe("Open");
    expect(dbSession.rows[0]?.opened_at).toBeTruthy();
    expect(dbSession.rows[0]?.opened_by_user_id).toBe(SEED.lecturer);

    const qrTokens = await pool.query(
      `SELECT state FROM qr_session_tokens WHERE class_session_id = $1 AND state = 'Valid'`,
      [SEED.sessionScheduled],
    );
    expect((qrTokens.rowCount ?? 0)).toBeGreaterThan(0);
  });

  it("TC-FR-07-005 TC-AC-01-003: invalid open transitions return 409 without state mutation", async () => {
    const token = await login(app, "lecturer@attendly.local");
    const openSessionId = await insertSession(pool, "Open");
    const closedSessionId = await insertSession(pool, "Closed");
    const cancelledSessionId = await insertSession(pool, "Cancelled");

    for (const sessionId of [openSessionId, closedSessionId, cancelledSessionId]) {
      const before = await pool.query(`SELECT state FROM class_sessions WHERE id = $1`, [sessionId]);
      const response = await app.inject({
        method: "POST",
        url: `/api/v1/class-sessions/${sessionId}/open`,
        headers: {
          authorization: `Bearer ${token}`,
          "idempotency-key": randomUUID(),
        },
      });
      expect(response.statusCode).toBe(409);
      const err = response.json() as { error: { code: string } };
      expect(err.error.code).toBe("InvalidSessionTransition");

      const after = await pool.query(`SELECT state FROM class_sessions WHERE id = $1`, [sessionId]);
      expect(after.rows[0]?.state).toBe(before.rows[0]?.state);
    }
  });

  it("TC-FR-07-009: concurrent open with same idempotency key yields single Open transition", async () => {
    const token = await login(app, "lecturer@attendly.local");
    const idempotencyKey = randomUUID();

    await pool.query(
      `UPDATE class_sessions SET state = 'Scheduled', opened_at = NULL, opened_by_user_id = NULL, closed_at = NULL, closed_by_user_id = NULL WHERE id = $1`,
      [SEED.sessionScheduled],
    );

    const headers = {
      authorization: `Bearer ${token}`,
      "idempotency-key": idempotencyKey,
    };

    const [first, second] = await Promise.all([
      app.inject({
        method: "POST",
        url: `/api/v1/class-sessions/${SEED.sessionScheduled}/open`,
        headers,
      }),
      app.inject({
        method: "POST",
        url: `/api/v1/class-sessions/${SEED.sessionScheduled}/open`,
        headers,
      }),
    ]);

    expect(first.statusCode).toBe(200);
    expect(second.statusCode).toBe(200);
    expect((first.json() as { data: { state: string } }).data.state).toBe("Open");
    expect((second.json() as { data: { state: string } }).data.state).toBe("Open");

    const dbSession = await pool.query(
      `SELECT state, opened_at, opened_by_user_id FROM class_sessions WHERE id = $1`,
      [SEED.sessionScheduled],
    );
    expect(dbSession.rows[0]?.state).toBe("Open");
    expect(dbSession.rows[0]?.opened_at).toBeTruthy();
  });

  it("TC-FR-08-003 TC-FR-08-004 TC-AC-05-002: close persists Closed state with summary counts", async () => {
    const token = await login(app, "lecturer@attendly.local");
    const sessionId = await insertSession(pool, "Open");

    const response = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${sessionId}/close`,
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
    });

    expect(response.statusCode).toBe(200);
    const body = response.json() as {
      data: {
        state: string;
        closedAt: string;
        summary: { present: number; late: number; manualPresent: number; absent: number };
      };
    };
    expect(body.data.state).toBe("Closed");
    expect(body.data.closedAt).toBeTruthy();
    expect(body.data.summary).toEqual(
      expect.objectContaining({
        present: expect.any(Number),
        late: expect.any(Number),
        manualPresent: expect.any(Number),
        absent: expect.any(Number),
      }),
    );

    const dbSession = await pool.query(
      `SELECT state, closed_at, closed_by_user_id FROM class_sessions WHERE id = $1`,
      [sessionId],
    );
    expect(dbSession.rows[0]?.state).toBe("Closed");
    expect(dbSession.rows[0]?.closed_at).toBeTruthy();
    expect(dbSession.rows[0]?.closed_by_user_id).toBe(SEED.lecturer);

    const invalidTokens = await pool.query(
      `SELECT COUNT(*)::int AS count FROM qr_session_tokens WHERE class_session_id = $1 AND state = 'Valid'`,
      [sessionId],
    );
    expect(invalidTokens.rows[0]?.count).toBe(0);
  });

  it("TC-FR-08-005: close rejects Scheduled/Cancelled; Closed is idempotent", async () => {
    const token = await login(app, "lecturer@attendly.local");
    const scheduledId = await insertSession(pool, "Scheduled");
    const cancelledId = await insertSession(pool, "Cancelled");
    const closedId = await insertSession(pool, "Closed");

    for (const sessionId of [scheduledId, cancelledId]) {
      const response = await app.inject({
        method: "POST",
        url: `/api/v1/class-sessions/${sessionId}/close`,
        headers: {
          authorization: `Bearer ${token}`,
          "idempotency-key": randomUUID(),
        },
      });
      expect(response.statusCode).toBe(409);
      expect((response.json() as { error: { code: string } }).error.code).toBe(
        "InvalidSessionTransition",
      );
    }

    const idempotentClose = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${closedId}/close`,
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
    });
    expect(idempotentClose.statusCode).toBe(200);
    expect((idempotentClose.json() as { data: { state: string } }).data.state).toBe("Closed");
  });

  it("TC-AC-01-002 TC-AC-05-001: open then close commits legal transitions with absent finalization", async () => {
    const token = await login(app, "lecturer@attendly.local");
    const sessionId = await insertSession(pool, "Scheduled");

    const openResponse = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${sessionId}/open`,
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
    });
    expect(openResponse.statusCode).toBe(200);

    const closeResponse = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${sessionId}/close`,
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
    });
    expect(closeResponse.statusCode).toBe(200);

    const summary = (closeResponse.json() as { data: { summary: { absent: number } } }).data.summary;
    expect(summary.absent).toBeGreaterThan(0);

    const absentRows = await pool.query(
      `SELECT COUNT(*)::int AS count FROM attendance_records WHERE class_session_id = $1 AND status = 'Absent'`,
      [sessionId],
    );
    expect(absentRows.rows[0]?.count).toBeGreaterThan(0);
  });

  it("TC-FR-07-006: student denied session open with 403", async () => {
    const token = await login(app, "student1@attendly.local");
    const sessionId = await insertSession(pool, "Scheduled");

    const response = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${sessionId}/open`,
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
    });
    expect(response.statusCode).toBe(403);

    const dbSession = await pool.query(`SELECT state FROM class_sessions WHERE id = $1`, [sessionId]);
    expect(dbSession.rows[0]?.state).toBe("Scheduled");
  });

  it("TC-AC-05-005: academic admin may close open session in scope", async () => {
    const token = await login(app, "academic-admin@attendly.local");
    const sessionId = await insertSession(pool, "Open");

    const response = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${sessionId}/close`,
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": randomUUID(),
      },
    });
    expect(response.statusCode).toBe(200);
    expect((response.json() as { data: { state: string } }).data.state).toBe("Closed");
  });

  it("TC-BR-02-003 TC-AC-05-002 BR-13: idempotent close does not duplicate absent rows", async () => {
    const token = await login(app, "lecturer@attendly.local");
    const sessionId = await insertSession(pool, "Open");
    const idempotencyKey = randomUUID();

    const firstClose = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${sessionId}/close`,
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": idempotencyKey,
      },
    });
    expect(firstClose.statusCode).toBe(200);
    const firstAbsent = (firstClose.json() as { data: { summary: { absent: number } } }).data.summary
      .absent;

    const secondClose = await app.inject({
      method: "POST",
      url: `/api/v1/class-sessions/${sessionId}/close`,
      headers: {
        authorization: `Bearer ${token}`,
        "idempotency-key": idempotencyKey,
      },
    });
    expect(secondClose.statusCode).toBe(200);
    const secondAbsent = (secondClose.json() as { data: { summary: { absent: number } } }).data.summary
      .absent;
    expect(secondAbsent).toBe(firstAbsent);

    const absentCount = await pool.query(
      `SELECT COUNT(*)::int AS count FROM attendance_records WHERE class_session_id = $1 AND status = 'Absent'`,
      [sessionId],
    );
    expect(absentCount.rows[0]?.count).toBe(firstAbsent);
  });

  it.skip("TC-FR-08-008 TC-BR-02-011 BR-21 AC-12: policy auto-close — owned by module-policy-engine", () => {
    // Scheduler-driven Open → Closed transition is implemented in the policy/scheduler slice (FR-09).
  });
});
