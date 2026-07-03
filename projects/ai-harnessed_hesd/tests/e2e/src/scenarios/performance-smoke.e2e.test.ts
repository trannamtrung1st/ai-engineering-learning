/**
 * Performance smoke E2E — HTTP contract and health telemetry baselines.
 *
 * Traceability: AC-20 AC-21 AC-22 NFR-01 NFR-02 NFR-03 NFR-16
 * TC-AC-20-004 TC-AC-21-005 TC-AC-21-006 TC-AC-21-007 TC-AC-21-008
 * TC-AC-22-005 TC-NFR-16-007 TC-NFR-16-009
 */
import { randomUUID } from "node:crypto";
import { performance } from "node:perf_hooks";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../../../../apps/api/src/app.js";
import { waitForSeededDb } from "../../../../apps/api/src/integration/fixtures/critical-path-fixtures.js";
import {
  PERF_SMOKE_SEED,
  PERF_STUDENTS_PER_SECTION,
  cleanupPerfSession,
  countEnrolledStudents,
  countSuccessfulCheckIns,
  ensurePerformanceSmokeHierarchy,
  insertPerfSession,
  loginAllPerfStudents,
  loginPerf,
  openPerfSession,
  perfStudentId,
  submitPerfCheckIn,
} from "../../../../apps/api/src/integration/fixtures/performance-smoke-fixtures.js";
import {
  evaluateMajorityCompletionGate,
  evaluateMedianLatencyGate,
  evaluateSuccessRateGate,
} from "../../../../apps/api/src/integration/performance/thresholds.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;

describe("performance smoke E2E — AC-20 AC-21 AC-22 NFR-01 NFR-02 NFR-16", { timeout: 120_000 }, () => {
  let app: FastifyInstance;
  let pool: pg.Pool;
  let lecturerToken: string;
  let studentTokens: Map<string, string>;
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
    await ensurePerformanceSmokeHierarchy(pool);
    lecturerToken = await loginPerf(app, "lecturer@attendly.local");
    studentTokens = await loginAllPerfStudents(app);
  }, 120_000);

  afterEach(async () => {
    for (const sessionId of createdSessions.splice(0)) {
      await cleanupPerfSession(pool, sessionId);
    }
  });

  afterAll(async () => {
    await app?.close();
    await pool?.end().catch(() => undefined);
  });

  it("TC-NFR-16-007: GET /v1/health returns operational status envelope", async () => {
    const response = await app.inject({ method: "GET", url: "/api/v1/health" });
    expect(response.statusCode).toBe(200);
    const body = response.json() as { status: string; db: string };
    expect(body.status).toBe("ok");
    expect(body.db).toBe("connected");
  });

  it("TC-AC-20-004 TC-AC-22-005: bulk rule-pass POST /v1/check-ins meets latency and success gates", async () => {
    const sessionId = await insertPerfSession(pool, PERF_SMOKE_SEED.sectionA);
    createdSessions.push(sessionId);
    const { qrPayload } = await openPerfSession(app, sessionId, lecturerToken);

    const latencies: number[] = [];
    let successes = 0;

    for (let i = 0; i < PERF_STUDENTS_PER_SECTION; i += 1) {
      const studentToken = studentTokens.get(perfStudentId(0, i))!;
      const start = performance.now();
      const response = await submitPerfCheckIn(app, {
        studentToken,
        qrToken: qrPayload,
        idempotencyKey: randomUUID(),
      });
      latencies.push(performance.now() - start);
      const body = response.json() as { data?: { outcome?: string } };
      if (response.statusCode === 200 && body.data?.outcome === "Success") {
        successes += 1;
      }
    }

    const latencyVerdict = evaluateMedianLatencyGate(latencies);
    const successVerdict = evaluateSuccessRateGate(successes, PERF_STUDENTS_PER_SECTION);
    expect(latencyVerdict.pass).toBe(true);
    expect(successVerdict.pass).toBe(true);
  });

  it("TC-NFR-16-009: roster exposes rejectedAttempts for failure triage", async () => {
    const sessionId = await insertPerfSession(pool, PERF_SMOKE_SEED.sectionA);
    createdSessions.push(sessionId);
    const { qrPayload } = await openPerfSession(app, sessionId, lecturerToken);

    const studentToken = studentTokens.get(perfStudentId(0, 0))!;
    await submitPerfCheckIn(app, { studentToken, qrToken: qrPayload, idempotencyKey: randomUUID() });
    await submitPerfCheckIn(app, {
      studentToken,
      qrToken: qrPayload,
      idempotencyKey: randomUUID(),
    });

    const roster = await app.inject({
      method: "GET",
      url: `/api/v1/class-sessions/${sessionId}/attendance`,
      headers: { authorization: `Bearer ${lecturerToken}` },
    });
    expect(roster.statusCode).toBe(200);
    const body = roster.json() as {
      data: { counts: { rejectedAttempts: number; present: number } };
    };
    expect(body.data.counts.rejectedAttempts).toBeGreaterThanOrEqual(1);
    expect(body.data.counts.present).toBeGreaterThanOrEqual(1);
  });

  it("TC-AC-21-005 NFR-02: GET /attendance reflects majority completion within 5 minutes", async () => {
    const sessionId = await insertPerfSession(pool, PERF_SMOKE_SEED.sectionA);
    createdSessions.push(sessionId);
    const { qrPayload } = await openPerfSession(app, sessionId, lecturerToken);
    const enrolled = await countEnrolledStudents(pool, PERF_SMOKE_SEED.sectionA);
    const majorityCount = Math.ceil(enrolled * 0.55);

    for (let i = 0; i < majorityCount; i += 1) {
      const studentToken = studentTokens.get(perfStudentId(0, i))!;
      await submitPerfCheckIn(app, { studentToken, qrToken: qrPayload, idempotencyKey: randomUUID() });
    }

    const roster = await app.inject({
      method: "GET",
      url: `/api/v1/class-sessions/${sessionId}/attendance`,
      headers: { authorization: `Bearer ${lecturerToken}` },
    });
    expect(roster.statusCode).toBe(200);
    const body = roster.json() as {
      data: {
        state: string;
        counts: { present: number; late: number };
        rows: unknown[];
      };
    };
    expect(body.data.state).toBe("Open");
    const completed = body.data.counts.present + body.data.counts.late;
    expect(completed).toBeGreaterThan(enrolled * 0.5);
    expect(body.data.rows.length).toBeGreaterThan(0);
  });

  it("TC-AC-21-006 NFR-02: WF-03 class-start flow achieves majority completion within 5-minute SLO", async () => {
    const sessionId = await insertPerfSession(pool, PERF_SMOKE_SEED.sectionA);
    createdSessions.push(sessionId);
    const { qrPayload } = await openPerfSession(app, sessionId, lecturerToken);
    const enrolled = await countEnrolledStudents(pool, PERF_SMOKE_SEED.sectionA);

    for (let i = 0; i < PERF_STUDENTS_PER_SECTION; i += 1) {
      const studentToken = studentTokens.get(perfStudentId(0, i))!;
      const response = await submitPerfCheckIn(app, {
        studentToken,
        qrToken: qrPayload,
        idempotencyKey: randomUUID(),
      });
      expect(response.statusCode).toBe(200);
    }

    const completed = await countSuccessfulCheckIns(pool, sessionId);
    const verdict = evaluateMajorityCompletionGate(completed, enrolled);
    expect(verdict.pass).toBe(true);
    expect(completed).toBe(PERF_STUDENTS_PER_SECTION);
  });

  it("TC-AC-21-007 NFR-02: majority completion gate fails when fewer than 50% check in", async () => {
    const sessionId = await insertPerfSession(pool, PERF_SMOKE_SEED.sectionA);
    createdSessions.push(sessionId);
    const { qrPayload } = await openPerfSession(app, sessionId, lecturerToken);
    const enrolled = await countEnrolledStudents(pool, PERF_SMOKE_SEED.sectionA);
    const minorityCount = Math.floor(enrolled * 0.4);

    for (let i = 0; i < minorityCount; i += 1) {
      const studentToken = studentTokens.get(perfStudentId(0, i))!;
      await submitPerfCheckIn(app, { studentToken, qrToken: qrPayload, idempotencyKey: randomUUID() });
    }

    const completed = await countSuccessfulCheckIns(pool, sessionId);
    const failVerdict = evaluateMajorityCompletionGate(completed, enrolled);
    expect(failVerdict.pass).toBe(false);
    expect(completed).toBeLessThanOrEqual(enrolled * 0.5);

    const controlCompleted = minorityCount + Math.ceil(enrolled * 0.15);
    for (let i = minorityCount; i < controlCompleted; i += 1) {
      const studentToken = studentTokens.get(perfStudentId(0, i))!;
      await submitPerfCheckIn(app, { studentToken, qrToken: qrPayload, idempotencyKey: randomUUID() });
    }
    const passVerdict = evaluateMajorityCompletionGate(
      await countSuccessfulCheckIns(pool, sessionId),
      enrolled,
    );
    expect(passVerdict.pass).toBe(true);
  });

  it("TC-AC-21-008 NFR-02: non-Student roles denied POST /check-ins", async () => {
    const sessionId = await insertPerfSession(pool, PERF_SMOKE_SEED.sectionA);
    createdSessions.push(sessionId);
    const { qrPayload } = await openPerfSession(app, sessionId, lecturerToken);
    const adminToken = await loginPerf(app, "academic-admin@attendly.local");

    const lecturerAttempt = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: {
        authorization: `Bearer ${lecturerToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: { qrToken: qrPayload, clientTimestamp: new Date().toISOString() },
    });
    expect(lecturerAttempt.statusCode).toBe(403);

    const adminAttempt = await app.inject({
      method: "POST",
      url: "/api/v1/check-ins",
      headers: {
        authorization: `Bearer ${adminToken}`,
        "idempotency-key": randomUUID(),
      },
      payload: { qrToken: qrPayload, clientTimestamp: new Date().toISOString() },
    });
    expect(adminAttempt.statusCode).toBe(403);

    const studentToken = studentTokens.get(perfStudentId(0, 0))!;
    const studentResponse = await submitPerfCheckIn(app, {
      studentToken,
      qrToken: qrPayload,
      idempotencyKey: randomUUID(),
    });
    expect(studentResponse.statusCode).toBe(200);

    const attemptCount = await pool.query<{ count: number }>(
      `SELECT COUNT(*)::int AS count FROM check_in_attempts WHERE class_session_id = $1`,
      [sessionId],
    );
    expect(attemptCount.rows[0]?.count).toBe(1);
  });
});
