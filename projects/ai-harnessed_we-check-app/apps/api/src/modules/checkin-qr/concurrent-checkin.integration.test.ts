import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import {
  AttendanceStatus,
  ErrorCode,
  SESSION_COOKIE_NAME,
  UserRole,
} from "@wecheck/domain";
import {
  createPool,
  setPool,
  closePool,
  type DbPool,
} from "../../infra/db.js";
import { runMigrations } from "../../infra/migrate.js";
import { buildApp } from "../../server.js";
import {
  createTestUser,
  SessionStore,
  truncateAuthTables,
} from "../../auth/session-store.js";
import { resetClock } from "../../infra/clock.js";
import { now } from "../../infra/clock.js";
import { truncateRosterTables } from "../roster-enrollment/roster-service.js";
import { SessionService } from "../session-management/session-service.js";
import { CheckInService, truncateCheckInTables } from "./check-in-service.js";
import { withIntegrationTestDbReset } from "../../infra/integration-test-lock.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

const CLASS_HESD_01 = "10000000-0000-4000-8000-000000000101";
const SUBJECT_SWE_101 = "20000000-0000-4000-8000-000000000201";
const ROOM_LAT = 10.762622;
const ROOM_LNG = 106.660172;
const IN_RADIUS_LAT = 10.7627;
const IN_RADIUS_LNG = 106.6602;

/**
 * Traceability: AC-09 NFR-02 FR-09 BR-04
 * Cases: TC-AC-09-003 TC-AC-09-005
 */
describe("concurrent check-in (AC-09c, NFR-02)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let sessionService: SessionService;
  let checkInService: CheckInService;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    sessionService = new SessionService(db);
    checkInService = new CheckInService(db);
  });

  after(async () => {
    await sessionService.qr.stopAll();
    resetClock();
    await app.close();
    await closePool();
  });

  async function seedActiveWithTwoTokens(): Promise<{
    sessionId: string;
    studentId: string;
    studentCookie: string;
    tokenIds: [string, string];
  }> {
    await withIntegrationTestDbReset(db, async () => {
      await sessionService.qr.stopAll();
      await truncateCheckInTables(db);
      await truncateRosterTables(db);
      await truncateAuthTables(db);
      resetClock();

      await db.query(
        `INSERT INTO classes (id, code, name) VALUES ($1, 'HESD-01', 'HESD Cohort A')
         ON CONFLICT (id) DO NOTHING`,
        [CLASS_HESD_01],
      );
      await db.query(
        `INSERT INTO subjects (id, code, name) VALUES ($1, 'SWE-101', 'SWE-101')
         ON CONFLICT (id) DO NOTHING`,
        [SUBJECT_SWE_101],
      );
    });

    const instructorId = await createTestUser(db, {
      institutionalId: "GV2026100",
      displayName: "Instructor",
      email: "inst-concurrent@example.edu.vn",
      role: UserRole.Instructor,
    });
    await db.query(
      `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
       VALUES ($1, $2, $3)`,
      [instructorId, CLASS_HESD_01, SUBJECT_SWE_101],
    );

    const studentId = await createTestUser(db, {
      institutionalId: "SV2026100",
      displayName: "Student Concurrent",
      email: "student-concurrent@example.edu.vn",
      role: UserRole.Student,
    });
    await db.query(
      `INSERT INTO enrollments (student_id, class_id, subject_id) VALUES ($1, $2, $3)`,
      [studentId, CLASS_HESD_01, SUBJECT_SWE_101],
    );

    const store = new SessionStore(db);
    const studentSession = await store.createSession(studentId);

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Concurrent test",
        roomName: "A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: new Date(now().getTime() + 3600000).toISOString(),
      },
      instructorId,
      UserRole.Instructor,
    );
    await sessionService.open(created.id, instructorId, UserRole.Instructor);

    const qr1 = await sessionService.getCurrentQr(created.id, instructorId, UserRole.Instructor);
    const token2Id = randomUUID();
    const issuedAt = new Date();
    const expiresAt = new Date(issuedAt.getTime() + 30_000);
    await db.query(
      `INSERT INTO qr_tokens (id, session_id, status, issued_at, expires_at)
       VALUES ($1, $2, 'Valid', $3, $4)`,
      [token2Id, created.id, issuedAt, expiresAt],
    );

    return {
      sessionId: created.id,
      studentId,
      studentCookie: `${SESSION_COOKIE_NAME}=${studentSession.id}`,
      tokenIds: [qr1.tokenId, token2Id],
    };
  }

  it("parallel duplicate check-in yields exactly one Present (TC-AC-09-003, NFR-02)", async () => {
    const { sessionId, studentId, studentCookie, tokenIds } =
      await seedActiveWithTwoTokens();

    const payload = (tokenId: string) => ({
      tokenId,
      latitude: IN_RADIUS_LAT,
      longitude: IN_RADIUS_LNG,
      spoofMetadata: { accuracyMeters: 12, platform: "android" },
    });

    const [res1, res2] = await Promise.all([
      app.inject({
        method: "POST",
        url: "/api/v1/check-in",
        headers: { cookie: studentCookie },
        payload: payload(tokenIds[0]),
      }),
      app.inject({
        method: "POST",
        url: "/api/v1/check-in",
        headers: { cookie: studentCookie },
        payload: payload(tokenIds[1]),
      }),
    ]);

    const outcomes = [res1, res2].map((r) => r.json<{ outcome: string }>().outcome);
    const successCount = outcomes.filter((o) => o === "Success").length;
    const duplicateCount = outcomes.filter((o) => o === ErrorCode.DuplicateCheckIn).length;

    assert.equal(successCount, 1);
    assert.equal(duplicateCount, 1);

    const present = await db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM attendance_records
       WHERE session_id = $1 AND student_id = $2 AND status = $3`,
      [sessionId, studentId, AttendanceStatus.Present],
    );
    assert.equal(present.rows[0]?.count, "1");

    const attempts = await db.query<{ outcome: string }>(
      `SELECT outcome FROM check_in_attempts
       WHERE session_id = $1 AND student_id = $2 ORDER BY attempted_at`,
      [sessionId, studentId],
    );
    assert.equal(attempts.rows.length, 2);
    const attemptOutcomes = attempts.rows.map((r) => r.outcome);
    assert.ok(attemptOutcomes.includes("Success"));
    assert.ok(attemptOutcomes.includes(ErrorCode.DuplicateCheckIn));
  });

  it("20 parallel CheckInService.submit calls produce one Present (TC-AC-09-005)", async () => {
    const { sessionId, studentId, tokenIds } = await seedActiveWithTwoTokens();

    const tokens = [...tokenIds];
    while (tokens.length < 20) {
      await sessionService.qr.rotate(sessionId);
      const qr = await sessionService.getCurrentQr(
        sessionId,
        (await db.query<{ instructor_id: string }>(
          `SELECT instructor_id FROM sessions WHERE id = $1`,
          [sessionId],
        )).rows[0]!.instructor_id,
        UserRole.Instructor,
      );
      tokens.push(qr.tokenId);
    }

    const results = await Promise.all(
      tokens.slice(0, 20).map((tokenId) =>
        checkInService.submit(
          {
            tokenId,
            latitude: IN_RADIUS_LAT,
            longitude: IN_RADIUS_LNG,
            spoofMetadata: { accuracyMeters: 12, platform: "android" },
          },
          studentId,
        ),
      ),
    );

    const successCount = results.filter((r) => r.outcome === "Success").length;
    assert.equal(successCount, 1);

    const present = await db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM attendance_records
       WHERE session_id = $1 AND student_id = $2 AND status = $3`,
      [sessionId, studentId, AttendanceStatus.Present],
    );
    assert.equal(present.rows[0]?.count, "1");
  });
});
