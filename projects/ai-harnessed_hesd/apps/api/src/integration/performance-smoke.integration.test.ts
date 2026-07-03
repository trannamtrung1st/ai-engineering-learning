/**
 * Performance and reliability smoke — class-start burst, latency, success-rate, telemetry.
 *
 * Traceability: AC-20 AC-21 AC-22 NFR-01 NFR-02 NFR-03 NFR-16
 * TC-AC-20-001 TC-AC-20-002 TC-AC-20-003 TC-AC-21-001 TC-AC-21-002 TC-AC-21-003 TC-AC-21-004
 * TC-AC-22-001 TC-AC-22-004 TC-NFR-01-001 TC-NFR-01-003 TC-NFR-03-001 TC-NFR-03-004
 * TC-NFR-16-001 TC-NFR-16-005 TC-NFR-16-015
 */
import { randomUUID } from "node:crypto";
import { performance } from "node:perf_hooks";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../app.js";
import { getOperationalTelemetrySnapshot } from "../modules/realtime-delivery/index.js";
import {
  PERF_SMOKE_SEED,
  PERF_SMOKE_EMAILS,
  PERF_STUDENTS_PER_SECTION,
  cleanupPerfSession,
  countEnrolledStudents,
  countSuccessfulCheckIns,
  ensureItAdminPreviewActor,
  ensurePerformanceSmokeHierarchy,
  insertPerfSession,
  loginAllPerfStudents,
  loginPerf,
  mapWithConcurrency,
  openPerfSession,
  PERF_BURST_CONCURRENCY,
  perfStudentId,
  submitPerfCheckIn,
} from "./fixtures/performance-smoke-fixtures.js";
import { waitForSeededDb } from "./fixtures/critical-path-fixtures.js";
import {
  buildPerformanceSmokeSnapshot,
  publishPerformanceSmokeSnapshot,
} from "./performance/snapshot.js";
import {
  evaluateMajorityCompletionGate,
  evaluateMedianLatencyGate,
  evaluateSuccessRateGate,
  isWithinCompletionWindow,
} from "./performance/thresholds.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;

type CheckInAttemptResult = {
  studentId: string;
  sessionId: string;
  elapsedMs: number;
  success: boolean;
  statusCode: number;
};

describe(
  "performance smoke — AC-20 AC-21 AC-22 NFR-01 NFR-02 NFR-03 NFR-16",
  { timeout: 120_000 },
  () => {
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
    await ensureItAdminPreviewActor(pool);
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

  async function runClassStartBurst(): Promise<{
    results: CheckInAttemptResult[];
    sessions: Array<{ sessionId: string; sectionId: string; openedAt: Date }>;
  }> {
    const sessionA = await insertPerfSession(pool, PERF_SMOKE_SEED.sectionA);
    const sessionB = await insertPerfSession(pool, PERF_SMOKE_SEED.sectionB);
    createdSessions.push(sessionA, sessionB);

    const [openA, openB] = await Promise.all([
      openPerfSession(app, sessionA, lecturerToken),
      openPerfSession(app, sessionB, lecturerToken),
    ]);

    const sessions = [
      { sessionId: sessionA, sectionId: PERF_SMOKE_SEED.sectionA, openedAt: new Date(openA.openedAt) },
      { sessionId: sessionB, sectionId: PERF_SMOKE_SEED.sectionB, openedAt: new Date(openB.openedAt) },
    ];

    const burstJobs: Array<{
      studentId: string;
      sessionId: string;
      studentToken: string;
      qrToken: string;
    }> = [];

    for (let section = 0; section < 2; section += 1) {
      const sessionId = section === 0 ? sessionA : sessionB;
      const qrToken = section === 0 ? openA.qrPayload : openB.qrPayload;
      for (let i = 0; i < PERF_STUDENTS_PER_SECTION; i += 1) {
        const studentId = perfStudentId(section as 0 | 1, i);
        const studentToken = studentTokens.get(studentId);
        if (!studentToken) {
          throw new Error(`Missing token for student ${studentId}`);
        }
        burstJobs.push({ studentId, sessionId, studentToken, qrToken });
      }
    }

    const results = await mapWithConcurrency(burstJobs, PERF_BURST_CONCURRENCY, async (job) => {
      const start = performance.now();
      const response = await submitPerfCheckIn(app, {
        studentToken: job.studentToken,
        qrToken: job.qrToken,
        idempotencyKey: randomUUID(),
      });
      const elapsedMs = performance.now() - start;
      const body = response.json() as {
        data?: { outcome?: string; attendanceStatus?: string };
      };
      const success =
        response.statusCode === 200 &&
        body.data?.outcome === "Success" &&
        (body.data.attendanceStatus === "Present" || body.data.attendanceStatus === "Late");
      return {
        studentId: job.studentId,
        sessionId: job.sessionId,
        elapsedMs,
        success,
        statusCode: response.statusCode,
      };
    });

    return { results, sessions };
  }

  it("TC-AC-20-003 TC-AC-21-001 TC-AC-21-004 TC-AC-22-004 TC-NFR-01-003 TC-NFR-02 TC-NFR-03-004 TC-NFR-16-005: class-start burst meets latency, success, completion, and telemetry gates", async () => {
    const { results, sessions } = await runClassStartBurst();
    const successLatencies = results.filter((r) => r.success).map((r) => r.elapsedMs);
    expect(successLatencies.length).toBeGreaterThan(0);

    const latencyVerdict = evaluateMedianLatencyGate(successLatencies);
    expect(latencyVerdict.pass).toBe(true);
    expect(latencyVerdict.actual).toBeLessThan(30_000);

    const successes = results.filter((r) => r.success).length;
    const successVerdict = evaluateSuccessRateGate(successes, results.length);
    expect(successVerdict.pass).toBe(true);
    expect(successes / results.length).toBeGreaterThanOrEqual(0.99);

    for (const session of sessions) {
      const enrolled = await countEnrolledStudents(pool, session.sectionId);
      const completed = await countSuccessfulCheckIns(pool, session.sessionId);
      const completionVerdict = evaluateMajorityCompletionGate(completed, enrolled);
      expect(completionVerdict.pass).toBe(true);
      expect(completed).toBeGreaterThan(enrolled * 0.5);

      const checkInTimes = await pool.query<{ check_in_at: Date }>(
        `
        SELECT check_in_at
        FROM attendance_records
        WHERE class_session_id = $1 AND status IN ('Present', 'Late')
        `,
        [session.sessionId],
      );
      for (const row of checkInTimes.rows) {
        expect(isWithinCompletionWindow(row.check_in_at, session.openedAt)).toBe(true);
      }
    }

    expect(results.filter((r) => r.success).length).toBe(PERF_STUDENTS_PER_SECTION * 2);

    const sessionId = sessions[0]!.sessionId;
    const telemetry = getOperationalTelemetrySnapshot({ classSessionId: sessionId });
    expect(telemetry.some((event) => event.type === "SessionOpened")).toBe(true);
    expect(telemetry.some((event) => event.type === "QrTokenIssued")).toBe(true);
    expect(telemetry.filter((event) => event.type === "CheckInAttemptRecorded").length).toBeGreaterThan(0);

    const rosterResponse = await app.inject({
      method: "GET",
      url: `/api/v1/class-sessions/${sessionId}/attendance`,
      headers: { authorization: `Bearer ${lecturerToken}` },
    });
    expect(rosterResponse.statusCode).toBe(200);
    const roster = rosterResponse.json() as {
      data: { counts: { present: number; late: number } };
    };
    expect(roster.data.counts.present + roster.data.counts.late).toBeGreaterThan(
      PERF_STUDENTS_PER_SECTION * 0.5,
    );

    const snapshot = buildPerformanceSmokeSnapshot({
      sliceId: "test-nfr-performance-reliability-smoke",
      sampleSize: results.length,
      sessionCount: sessions.length,
      verdicts: {
        medianCheckInMs: latencyVerdict,
        validSuccessRate: successVerdict,
        majorityCompletionRate: evaluateMajorityCompletionGate(
          await countSuccessfulCheckIns(pool, sessions[0]!.sessionId),
          await countEnrolledStudents(pool, sessions[0]!.sectionId),
        ),
      },
    });
    if (process.env.PERF_SMOKE_PUBLISH_METRICS === "true") {
      const filePath = publishPerformanceSmokeSnapshot(snapshot);
      expect(filePath).toContain("performance-smoke");
    }
    expect(snapshot.overallPass).toBe(true);
  });

  it("TC-AC-21-003 NFR-02: session open transition records openedAt as T=0 for completion window", async () => {
    const sessionId = await insertPerfSession(pool, PERF_SMOKE_SEED.sectionA);
    createdSessions.push(sessionId);

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
      data: { state: string; openedAt: string };
    };
    expect(body.data.state).toBe("Open");
    expect(body.data.openedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);

    const dbRow = await pool.query<{ state: string; opened_at: Date; opened_by_user_id: string }>(
      `SELECT state, opened_at, opened_by_user_id FROM class_sessions WHERE id = $1`,
      [sessionId],
    );
    expect(dbRow.rows[0]?.state).toBe("Open");
    expect(dbRow.rows[0]?.opened_at).toBeTruthy();
    expect(dbRow.rows[0]?.opened_by_user_id).toBe(PERF_SMOKE_SEED.lecturer);

    const openedAt = new Date(body.data.openedAt);
    const withinWindow = new Date(openedAt.getTime() + 4 * 60_000);
    expect(isWithinCompletionWindow(withinWindow, openedAt)).toBe(true);
  });

  it("TC-AC-21-002 NFR-02: attendance ledger computes majority completion within 5-minute window", async () => {
    const sessionId = await insertPerfSession(pool, PERF_SMOKE_SEED.sectionA);
    createdSessions.push(sessionId);
    const { qrPayload, openedAt } = await openPerfSession(app, sessionId, lecturerToken);
    const openedAtDate = new Date(openedAt);
    const enrolled = await countEnrolledStudents(pool, PERF_SMOKE_SEED.sectionA);
    const majorityCount = Math.ceil(enrolled * 0.55);

    for (let i = 0; i < majorityCount; i += 1) {
      const studentToken = studentTokens.get(perfStudentId(0, i))!;
      const response = await submitPerfCheckIn(app, {
        studentToken,
        qrToken: qrPayload,
        idempotencyKey: randomUUID(),
      });
      expect(response.statusCode).toBe(200);
    }

    const completed = await countSuccessfulCheckIns(pool, sessionId);
    const completionVerdict = evaluateMajorityCompletionGate(completed, enrolled);
    expect(completionVerdict.pass).toBe(true);
    expect(completed).toBeGreaterThan(enrolled * 0.5);

    const records = await pool.query<{ check_in_at: Date; status: string }>(
      `
      SELECT check_in_at, status
      FROM attendance_records
      WHERE class_session_id = $1 AND status IN ('Present', 'Late')
      `,
      [sessionId],
    );
    expect(records.rows.length).toBe(completed);
    for (const row of records.rows) {
      expect(isWithinCompletionWindow(row.check_in_at, openedAtDate)).toBe(true);
    }
  });

  it("TC-NFR-16-015 NFR-16: ITAdmin institution scope reads technical audit logs", async () => {
    const sessionId = await insertPerfSession(pool, PERF_SMOKE_SEED.sectionA);
    createdSessions.push(sessionId);
    await openPerfSession(app, sessionId, lecturerToken);

    const itAdminToken = await loginPerf(app, PERF_SMOKE_EMAILS.itAdmin);
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/audit-logs?page=1&pageSize=25&actionType=SessionOpen",
      headers: { authorization: `Bearer ${itAdminToken}` },
    });
    expect(response.statusCode).toBe(200);
    const body = response.json() as { data: unknown[]; error?: { code: string } | null };
    expect(body.error?.code).not.toBe("OutOfScope");
    expect(Array.isArray(body.data)).toBe(true);
  });

  it("TC-AC-22-004 TC-AC-21-004 NFR-02: idempotent replays return success without duplicate attendance rows", async () => {
    const sessionId = await insertPerfSession(pool, PERF_SMOKE_SEED.sectionA);
    createdSessions.push(sessionId);
    const { qrPayload } = await openPerfSession(app, sessionId, lecturerToken);
    const studentId = perfStudentId(0, 0);
    const studentToken = studentTokens.get(studentId)!;
    const idempotencyKey = randomUUID();

    const first = await submitPerfCheckIn(app, { studentToken, qrToken: qrPayload, idempotencyKey });
    const replay = await submitPerfCheckIn(app, { studentToken, qrToken: qrPayload, idempotencyKey });
    expect(first.statusCode).toBe(200);
    expect(replay.statusCode).toBe(200);

    const duplicate = await submitPerfCheckIn(app, {
      studentToken,
      qrToken: qrPayload,
      idempotencyKey: randomUUID(),
    });
    expect(duplicate.statusCode).toBe(409);

    const rowCount = await pool.query<{ count: number }>(
      `
      SELECT COUNT(*)::int AS count
      FROM attendance_records
      WHERE class_session_id = $1 AND student_user_id = $2
      `,
      [sessionId, studentId],
    );
    expect(rowCount.rows[0]?.count).toBe(1);
  });
  },
);
