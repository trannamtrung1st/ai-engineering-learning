/**
 * REG-01/02/03 critical-path integration suite — session transitions, check-in validation
 * ordering, duplicate prevention, close-time absent finalization, attempt audit coverage.
 *
 * Traceability: AC-01 AC-04 AC-08 AC-12 AC-18 NFR-07
 * TC-AC-01-002 TC-AC-01-003 TC-AC-01-004 TC-AC-04-001 TC-AC-04-002 TC-AC-04-003 TC-AC-04-004
 * TC-AC-08-001 TC-AC-08-002 TC-AC-08-003 TC-AC-08-004 TC-AC-12-001 TC-AC-12-002 TC-AC-12-003
 * TC-AC-12-004 TC-AC-18-001 TC-AC-18-002 TC-AC-18-003 TC-AC-18-004 TC-AC-18-005
 * TC-NFR-07-001 TC-NFR-07-002 TC-NFR-07-003 TC-NFR-07-005
 */
import { randomUUID } from "node:crypto";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { FastifyInstance } from "fastify";
import pg from "pg";
import { buildApp } from "../app.js";
import {
  CRITICAL_PATH_EMAILS,
  CRITICAL_PATH_SEED,
  cleanupSession,
  closeSession,
  countAttendanceRecords,
  ensureCriticalPathHierarchy,
  expireToken,
  insertSession,
  listAttemptOutcomes,
  login,
  openSession,
  submitCheckIn,
  waitForSeededDb,
} from "./fixtures/critical-path-fixtures.js";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;

describe("REG critical path — AC-01 AC-04 AC-08 AC-12 AC-18 NFR-07", () => {
  let app: FastifyInstance;
  let pool: pg.Pool;
  let lecturerToken: string;
  let student1Token: string;
  let student2Token: string;
  let student3Token: string;
  let unenrolledToken: string;
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
    await ensureCriticalPathHierarchy(pool);
    lecturerToken = await login(app, CRITICAL_PATH_EMAILS.lecturer);
    student1Token = await login(app, CRITICAL_PATH_EMAILS.student1);
    student2Token = await login(app, CRITICAL_PATH_EMAILS.student2);
    student3Token = await login(app, CRITICAL_PATH_EMAILS.student3);
    unenrolledToken = await login(app, CRITICAL_PATH_EMAILS.unenrolled);
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

  describe("REG-01 session open/close transition guards — AC-01", () => {
    it("TC-AC-01-002 TC-AC-01-003: Scheduled→Open→Closed commits legal transitions with persistence side effects", async () => {
      const sessionId = track(await insertSession(pool, "Scheduled"));

      const openResponse = await app.inject({
        method: "POST",
        url: `/api/v1/class-sessions/${sessionId}/open`,
        headers: {
          authorization: `Bearer ${lecturerToken}`,
          "idempotency-key": randomUUID(),
        },
      });
      expect(openResponse.statusCode).toBe(200);
      const openBody = openResponse.json() as {
        data: { state: string; openedAt: string; qr: { qrPayload: string } };
      };
      expect(openBody.data.state).toBe("Open");
      expect(openBody.data.openedAt).toBeTruthy();
      expect(openBody.data.qr.qrPayload).toBeTruthy();

      const dbOpen = await pool.query(
        `SELECT state, opened_at, opened_by_user_id FROM class_sessions WHERE id = $1`,
        [sessionId],
      );
      expect(dbOpen.rows[0]?.state).toBe("Open");
      expect(dbOpen.rows[0]?.opened_at).toBeTruthy();
      expect(dbOpen.rows[0]?.opened_by_user_id).toBe(CRITICAL_PATH_SEED.lecturer);

      const closeResponse = await closeSession(app, sessionId, lecturerToken);
      expect(closeResponse.statusCode).toBe(200);
      const closeBody = closeResponse.json() as {
        data: { state: string; closedAt: string; summary: { absent: number } };
      };
      expect(closeBody.data.state).toBe("Closed");
      expect(closeBody.data.closedAt).toBeTruthy();
      expect(closeBody.data.summary.absent).toBeGreaterThan(0);

      const dbClosed = await pool.query(
        `SELECT state, closed_at, closed_by_user_id FROM class_sessions WHERE id = $1`,
        [sessionId],
      );
      expect(dbClosed.rows[0]?.state).toBe("Closed");
      expect(dbClosed.rows[0]?.closed_at).toBeTruthy();
      expect(dbClosed.rows[0]?.closed_by_user_id).toBe(CRITICAL_PATH_SEED.lecturer);
    });

    it("TC-AC-01-003: invalid open transitions reject without state mutation", async () => {
      for (const state of ["Open", "Closed"] as const) {
        const sessionId = track(await insertSession(pool, state));
        const before = await pool.query(`SELECT state FROM class_sessions WHERE id = $1`, [sessionId]);
        const response = await app.inject({
          method: "POST",
          url: `/api/v1/class-sessions/${sessionId}/open`,
          headers: {
            authorization: `Bearer ${lecturerToken}`,
            "idempotency-key": randomUUID(),
          },
        });
        expect(response.statusCode).toBe(409);
        expect((response.json() as { error: { code: string } }).error.code).toBe(
          "InvalidSessionTransition",
        );
        const after = await pool.query(`SELECT state FROM class_sessions WHERE id = $1`, [sessionId]);
        expect(after.rows[0]?.state).toBe(before.rows[0]?.state);
      }
    });
  });

  describe("REG-02 QR TTL and expired-token rejection — AC-04 AC-18", () => {
    it("TC-AC-04-001 TC-AC-18-001 TC-AC-18-002: ExpiredQr persists failed attempt without attendance row", async () => {
      const sessionId = track(await insertSession(pool, "Scheduled"));
      const qr = await openSession(app, sessionId, lecturerToken);
      await expireToken(pool, sessionId, qr.qrPayload);

      const requestId = randomUUID();
      const response = await submitCheckIn(app, {
        studentToken: student1Token,
        qrToken: qr.qrPayload,
        requestId,
      });
      expect(response.statusCode).toBe(422);
      expect((response.json() as { error: { code: string } }).error.code).toBe("ExpiredQr");

      const attempts = await pool.query<{ outcome: string; correlation_id: string | null }>(
        `SELECT outcome, correlation_id FROM check_in_attempts WHERE class_session_id = $1 AND student_user_id = $2`,
        [sessionId, CRITICAL_PATH_SEED.student1],
      );
      expect(attempts.rowCount).toBe(1);
      expect(attempts.rows[0]?.outcome).toBe("ExpiredQr");
      expect(attempts.rows[0]?.correlation_id).toBeTruthy();

      expect(await countAttendanceRecords(pool, sessionId, CRITICAL_PATH_SEED.student1)).toBe(0);
    });

    it("TC-AC-04-002 TC-AC-18-003: wrong-session token yields NotEnrolled; unknown token yields InvalidQr", async () => {
      const sessionA = track(await insertSession(pool, "Scheduled", CRITICAL_PATH_SEED.sectionA));
      const sessionB = track(await insertSession(pool, "Scheduled", CRITICAL_PATH_SEED.sectionB));
      const qrA = await openSession(app, sessionA, lecturerToken);
      const qrB = await openSession(app, sessionB, lecturerToken);

      const wrongSection = await submitCheckIn(app, {
        studentToken: student1Token,
        qrToken: qrB.qrPayload,
      });
      expect(wrongSection.statusCode).toBe(422);
      expect((wrongSection.json() as { error: { code: string } }).error.code).toBe("NotEnrolled");
      expect(await listAttemptOutcomes(pool, sessionB, CRITICAL_PATH_SEED.student1)).toEqual([
        "NotEnrolled",
      ]);

      const invalid = await submitCheckIn(app, {
        studentToken: student1Token,
        qrToken: randomUUID(),
      });
      expect(invalid.statusCode).toBe(422);
      expect((invalid.json() as { error: { code: string } }).error.code).toBe("InvalidQr");

      const successControl = await submitCheckIn(app, {
        studentToken: student1Token,
        qrToken: qrA.qrPayload,
      });
      expect(successControl.statusCode).toBe(200);
    });

    it("TC-AC-04-003 TC-AC-18-004: post-close check-in logs SessionClosed without success row", async () => {
      const sessionId = track(await insertSession(pool, "Scheduled"));
      const qr = await openSession(app, sessionId, lecturerToken);
      expect((await closeSession(app, sessionId, lecturerToken)).statusCode).toBe(200);

      const response = await submitCheckIn(app, {
        studentToken: student1Token,
        qrToken: qr.qrPayload,
      });
      expect(response.statusCode).toBe(422);
      expect((response.json() as { error: { code: string } }).error.code).toBe("SessionClosed");
      expect(await listAttemptOutcomes(pool, sessionId, CRITICAL_PATH_SEED.student1)).toEqual([
        "SessionClosed",
      ]);
      const attendance = await pool.query<{ status: string }>(
        `SELECT status FROM attendance_records WHERE class_session_id = $1 AND student_user_id = $2`,
        [sessionId, CRITICAL_PATH_SEED.student1],
      );
      expect(attendance.rows[0]?.status).not.toMatch(/^(Present|Late)$/);
    });

    it("TC-AC-18-003: validation order short-circuits SessionNotOpen before ExpiredQr on Scheduled session", async () => {
      const sessionId = track(await insertSession(pool, "Scheduled"));
      const staleToken = randomUUID();
      await expireToken(pool, sessionId, staleToken);

      const response = await submitCheckIn(app, {
        studentToken: student1Token,
        qrToken: staleToken,
      });
      expect(response.statusCode).toBe(422);
      expect((response.json() as { error: { code: string } }).error.code).toBe("SessionNotOpen");
    });
  });

  describe("REG-03 duplicate prevention and idempotency — AC-08 NFR-07", () => {
    it("TC-AC-08-001 TC-AC-08-002 TC-NFR-07-002: duplicate check-in preserves original success row", async () => {
      const sessionId = track(await insertSession(pool, "Scheduled"));
      const qr = await openSession(app, sessionId, lecturerToken);

      const first = await submitCheckIn(app, {
        studentToken: student1Token,
        qrToken: qr.qrPayload,
        idempotencyKey: randomUUID(),
      });
      expect(first.statusCode).toBe(200);
      const before = await pool.query<{ status: string; check_in_at: Date }>(
        `SELECT status, check_in_at FROM attendance_records WHERE class_session_id = $1 AND student_user_id = $2`,
        [sessionId, CRITICAL_PATH_SEED.student1],
      );
      const beforeStatus = before.rows[0]?.status;
      const beforeAt = before.rows[0]?.check_in_at?.toISOString();

      const currentQr = await app.inject({
        method: "GET",
        url: `/api/v1/class-sessions/${sessionId}/qr/current`,
        headers: { authorization: `Bearer ${lecturerToken}` },
      });
      const freshToken = (currentQr.json() as { data: { qrPayload: string } }).data.qrPayload;

      const duplicate = await submitCheckIn(app, {
        studentToken: student1Token,
        qrToken: freshToken,
        idempotencyKey: randomUUID(),
      });
      expect(duplicate.statusCode).toBe(409);
      expect((duplicate.json() as { error: { code: string } }).error.code).toBe("DuplicateCheckIn");

      expect(await countAttendanceRecords(pool, sessionId, CRITICAL_PATH_SEED.student1)).toBe(1);
      const after = await pool.query<{ status: string; check_in_at: Date }>(
        `SELECT status, check_in_at FROM attendance_records WHERE class_session_id = $1 AND student_user_id = $2`,
        [sessionId, CRITICAL_PATH_SEED.student1],
      );
      expect(after.rows[0]?.status).toBe(beforeStatus);
      expect(after.rows[0]?.check_in_at?.toISOString()).toBe(beforeAt);
      expect(await listAttemptOutcomes(pool, sessionId, CRITICAL_PATH_SEED.student1)).toEqual([
        "Success",
        "DuplicateCheckIn",
      ]);
    });

    it("TC-AC-01-004 TC-AC-04-004 TC-AC-08-003 TC-NFR-07-001: concurrent first attempts yield one success per student-session", async () => {
      const sessionId = track(await insertSession(pool, "Scheduled"));
      const qr = await openSession(app, sessionId, lecturerToken);

      const [first, second] = await Promise.all([
        submitCheckIn(app, {
          studentToken: student1Token,
          qrToken: qr.qrPayload,
          idempotencyKey: randomUUID(),
        }),
        submitCheckIn(app, {
          studentToken: student1Token,
          qrToken: qr.qrPayload,
          idempotencyKey: randomUUID(),
        }),
      ]);

      const statuses = [first.statusCode, second.statusCode].sort();
      expect(statuses).toEqual([200, 409]);
      expect(await countAttendanceRecords(pool, sessionId, CRITICAL_PATH_SEED.student1)).toBe(1);
    });

    it("TC-AC-08-003 TC-AC-18-005 TC-NFR-07-003: concurrent duplicates after success each log failed attempts", async () => {
      const sessionId = track(await insertSession(pool, "Scheduled"));
      const qr = await openSession(app, sessionId, lecturerToken);
      expect(
        (
          await submitCheckIn(app, {
            studentToken: student1Token,
            qrToken: qr.qrPayload,
          })
        ).statusCode,
      ).toBe(200);

      const currentQr = await app.inject({
        method: "GET",
        url: `/api/v1/class-sessions/${sessionId}/qr/current`,
        headers: { authorization: `Bearer ${lecturerToken}` },
      });
      const freshToken = (currentQr.json() as { data: { qrPayload: string } }).data.qrPayload;

      const [dup1, dup2] = await Promise.all([
        submitCheckIn(app, {
          studentToken: student1Token,
          qrToken: freshToken,
          idempotencyKey: randomUUID(),
        }),
        submitCheckIn(app, {
          studentToken: student1Token,
          qrToken: freshToken,
          idempotencyKey: randomUUID(),
        }),
      ]);
      expect(dup1.statusCode).toBe(409);
      expect(dup2.statusCode).toBe(409);
      expect(await countAttendanceRecords(pool, sessionId, CRITICAL_PATH_SEED.student1)).toBe(1);
      const outcomes = await listAttemptOutcomes(pool, sessionId, CRITICAL_PATH_SEED.student1);
      expect(outcomes.filter((o) => o === "DuplicateCheckIn").length).toBeGreaterThanOrEqual(2);
    });

    it("TC-NFR-07-001 TC-NFR-07-003: idempotent replay returns prior success without second ledger row", async () => {
      const sessionId = track(await insertSession(pool, "Scheduled"));
      const qr = await openSession(app, sessionId, lecturerToken);
      const idempotencyKey = randomUUID();

      const first = await submitCheckIn(app, {
        studentToken: student2Token,
        qrToken: qr.qrPayload,
        idempotencyKey,
      });
      expect(first.statusCode).toBe(200);
      const firstBody = first.json() as { data: { attendanceStatus: string; checkInAt: string } };

      const replays = await Promise.all(
        Array.from({ length: 5 }, () =>
          submitCheckIn(app, {
            studentToken: student2Token,
            qrToken: qr.qrPayload,
            idempotencyKey,
          }),
        ),
      );
      for (const replay of replays) {
        expect(replay.statusCode).toBe(200);
        const body = replay.json() as { data: { attendanceStatus: string; checkInAt: string } };
        expect(body.data.attendanceStatus).toBe(firstBody.data.attendanceStatus);
        expect(body.data.checkInAt).toBe(firstBody.data.checkInAt);
      }
      expect(await countAttendanceRecords(pool, sessionId, CRITICAL_PATH_SEED.student2)).toBe(1);
    });
  });

  describe("Close-time absent finalization — AC-12", () => {
    it("TC-AC-12-001 TC-AC-12-002 TC-AC-12-003: unresolved enrolled students become Absent; Present rows preserved", async () => {
      const sessionId = track(await insertSession(pool, "Scheduled"));
      expect((await openSession(app, sessionId, lecturerToken)).qrPayload).toBeTruthy();

      await pool.query(
        `
        INSERT INTO attendance_records (
          id, class_session_id, class_section_id, student_user_id, status,
          check_in_method, check_in_at, last_modified_by_user_id
        )
        VALUES ($1, $2, $3, $4, 'Present', 'QR', now(), $4)
        `,
        [randomUUID(), sessionId, CRITICAL_PATH_SEED.sectionA, CRITICAL_PATH_SEED.student1],
      );

      await pool.query(
        `
        INSERT INTO attendance_records (
          id, class_session_id, class_section_id, student_user_id, status, last_modified_by_user_id
        )
        VALUES ($1, $2, $3, $4, 'Pending', $5)
        `,
        [
          randomUUID(),
          sessionId,
          CRITICAL_PATH_SEED.sectionA,
          CRITICAL_PATH_SEED.student2,
          CRITICAL_PATH_SEED.lecturer,
        ],
      );

      const closeResponse = await closeSession(app, sessionId, lecturerToken);
      expect(closeResponse.statusCode).toBe(200);
      const summary = (closeResponse.json() as { data: { summary: { absent: number } } }).data.summary;
      expect(summary.absent).toBeGreaterThan(0);

      const roster = await app.inject({
        method: "GET",
        url: `/api/v1/class-sessions/${sessionId}/attendance`,
        headers: { authorization: `Bearer ${lecturerToken}` },
      });
      const rows = (roster.json() as { data: { rows: { studentUserId: string; attendanceStatus: string }[] } })
        .data.rows;
      expect(rows.find((r) => r.studentUserId === CRITICAL_PATH_SEED.student1)?.attendanceStatus).toBe(
        "Present",
      );
      expect(rows.find((r) => r.studentUserId === CRITICAL_PATH_SEED.student2)?.attendanceStatus).toBe(
        "Absent",
      );
      expect(rows.find((r) => r.studentUserId === CRITICAL_PATH_SEED.student3)?.attendanceStatus).toBe(
        "Absent",
      );
    });

    it("TC-AC-12-004 TC-NFR-07-005: idempotent close does not duplicate absent rows", async () => {
      const sessionId = track(await insertSession(pool, "Open"));
      const idempotencyKey = randomUUID();

      const first = await closeSession(app, sessionId, lecturerToken, idempotencyKey);
      expect(first.statusCode).toBe(200);
      const firstAbsent = (first.json() as { data: { summary: { absent: number } } }).data.summary.absent;

      const second = await closeSession(app, sessionId, lecturerToken, idempotencyKey);
      expect(second.statusCode).toBe(200);
      const secondAbsent = (second.json() as { data: { summary: { absent: number } } }).data.summary
        .absent;
      expect(secondAbsent).toBe(firstAbsent);

      const absentCount = await pool.query<{ count: number }>(
        `SELECT COUNT(*)::int AS count FROM attendance_records WHERE class_session_id = $1 AND status = 'Absent'`,
        [sessionId],
      );
      expect(absentCount.rows[0]?.count).toBe(firstAbsent);
    });

    it("TC-NFR-07-005: in-flight success before close preserves one attendance record", async () => {
      const sessionId = track(await insertSession(pool, "Scheduled"));
      const qr = await openSession(app, sessionId, lecturerToken);

      const [checkInResult, closeResult] = await Promise.all([
        submitCheckIn(app, {
          studentToken: student3Token,
          qrToken: qr.qrPayload,
          idempotencyKey: randomUUID(),
        }),
        closeSession(app, sessionId, lecturerToken, randomUUID()),
      ]);

      expect([200, 422]).toContain(checkInResult.statusCode);
      expect(closeResult.statusCode).toBe(200);
      expect(await countAttendanceRecords(pool, sessionId, CRITICAL_PATH_SEED.student3)).toBeLessThanOrEqual(
        1,
      );

      const postClose = await submitCheckIn(app, {
        studentToken: student3Token,
        qrToken: qr.qrPayload,
        idempotencyKey: randomUUID(),
      });
      expect(postClose.statusCode).toBe(422);
      expect((postClose.json() as { error: { code: string } }).error.code).toBe("SessionClosed");
    });
  });

  describe("Attempt audit coverage — AC-18", () => {
    it("TC-AC-18-003: terminal failure matrix persists structured outcomes without success mutation", async () => {
      const openSessionId = track(await insertSession(pool, "Scheduled"));
      const openQr = await openSession(app, openSessionId, lecturerToken);
      await submitCheckIn(app, { studentToken: student1Token, qrToken: openQr.qrPayload });
      expect(await listAttemptOutcomes(pool, openSessionId, CRITICAL_PATH_SEED.student1)).toContain(
        "Success",
      );

      const currentQr = await app.inject({
        method: "GET",
        url: `/api/v1/class-sessions/${openSessionId}/qr/current`,
        headers: { authorization: `Bearer ${lecturerToken}` },
      });
      const freshToken = (currentQr.json() as { data: { qrPayload: string } }).data.qrPayload;
      await submitCheckIn(app, {
        studentToken: student1Token,
        qrToken: freshToken,
        idempotencyKey: randomUUID(),
      });
      expect(await listAttemptOutcomes(pool, openSessionId, CRITICAL_PATH_SEED.student1)).toContain(
        "DuplicateCheckIn",
      );

      const closedSessionId = track(await insertSession(pool, "Scheduled"));
      const closedQr = await openSession(app, closedSessionId, lecturerToken);
      await closeSession(app, closedSessionId, lecturerToken);
      await submitCheckIn(app, { studentToken: student2Token, qrToken: closedQr.qrPayload });
      expect(await listAttemptOutcomes(pool, closedSessionId, CRITICAL_PATH_SEED.student2)).toEqual([
        "SessionClosed",
      ]);

      const notEnrolledSession = track(await insertSession(pool, "Scheduled", CRITICAL_PATH_SEED.sectionA));
      const notEnrolledQr = await openSession(app, notEnrolledSession, lecturerToken);
      await submitCheckIn(app, { studentToken: unenrolledToken, qrToken: notEnrolledQr.qrPayload });
      expect(
        await listAttemptOutcomes(pool, notEnrolledSession, CRITICAL_PATH_SEED.unenrolledStudent),
      ).toEqual(["NotEnrolled"]);
    });
  });
});
