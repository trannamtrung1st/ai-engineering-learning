import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import {
  AttendanceStatus,
  ErrorCode,
  NotificationType,
  SESSION_COOKIE_NAME,
  SessionStatus,
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
import { withIntegrationTestDbReset } from "../../infra/integration-test-lock.js";
import { truncateRosterTables } from "../roster-enrollment/roster-service.js";
import { truncateSessionTables } from "../session-management/session-service.js";
import { NotificationService } from "./notification-service.js";
import {
  POLICY_KEY_ABSENCE_THRESHOLD,
  truncateNotificationTables,
} from "./repositories.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

const CLASS_HESD_01 = "10000000-0000-4000-8000-000000000101";
const SUBJECT_SWE_101 = "20000000-0000-4000-8000-000000000201";
const SUBJECT_TEST_101 = "20000000-0000-4000-8000-000000000202";

const ROOM_LAT = 10.762622;
const ROOM_LNG = 106.660172;

/**
 * Traceability: AC-16 FR-16 BR-05
 * Integration: TC-AC-16-003 TC-AC-16-004 TC-AC-16-005 TC-AC-16-006 TC-AC-16-018
 * TC-FR-16-002 TC-FR-16-003 TC-FR-16-004 TC-FR-16-016 TC-FR-16-017 TC-FR-16-019
 * TC-BR-05-002 TC-BR-05-003 TC-BR-05-004 TC-BR-05-016 TC-BR-05-017 TC-BR-05-018
 */
describe("notifications integration (AC-16, FR-16, BR-05)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let store: SessionStore;
  let notificationService: NotificationService;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    store = new SessionStore(db);
    notificationService = new NotificationService(db);
  });

  after(async () => {
    resetClock();
    await app.close();
    await closePool();
  });

  async function resetDb(afterTruncate?: () => Promise<void>): Promise<void> {
    await withIntegrationTestDbReset(db, async () => {
      await truncateNotificationTables(db);
      await truncateSessionTables(db);
      await truncateRosterTables(db);
      await truncateAuthTables(db);
      resetClock();
      await db.query(
        `INSERT INTO policy_settings (key, value) VALUES ($1, '20')
         ON CONFLICT (key) DO UPDATE SET value = '20'`,
        [POLICY_KEY_ABSENCE_THRESHOLD],
      );
      if (afterTruncate) await afterTruncate();
    });
  }

  async function seedReferenceData(): Promise<void> {
    await db.query(
      `INSERT INTO classes (id, code, name) VALUES ($1, 'HESD-2026-A', 'HESD Cohort A')
       ON CONFLICT (id) DO NOTHING`,
      [CLASS_HESD_01],
    );
    await db.query(
      `INSERT INTO subjects (id, code, name) VALUES
       ($1, 'SWE-101', 'Software Engineering 101'),
       ($2, 'TEST-101', 'Test Subject 101')
       ON CONFLICT (id) DO NOTHING`,
      [SUBJECT_SWE_101, SUBJECT_TEST_101],
    );
  }

  async function seedInstructor(): Promise<{ userId: string; cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId: "GV2026001",
      displayName: "Instructor One",
      email: "instructor@example.edu.vn",
      role: UserRole.Instructor,
    });
    await db.query(
      `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
       VALUES ($1, $2, $3), ($1, $2, $4)`,
      [userId, CLASS_HESD_01, SUBJECT_SWE_101, SUBJECT_TEST_101],
    );
    const session = await store.createSession(userId);
    return { userId, cookie: `${SESSION_COOKIE_NAME}=${session.id}` };
  }

  async function seedStudent(
    institutionalId: string,
    email: string,
    displayName: string,
  ): Promise<{ userId: string; cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId,
      displayName,
      email,
      role: UserRole.Student,
    });
    const session = await store.createSession(userId);
    return { userId, cookie: `${SESSION_COOKIE_NAME}=${session.id}` };
  }

  async function seedAdmin(): Promise<{ userId: string; cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId: "ADMIN001",
      displayName: "Admin User",
      email: "admin@example.edu.vn",
      role: UserRole.TrainingOfficeAdmin,
    });
    const session = await store.createSession(userId);
    return { userId, cookie: `${SESSION_COOKIE_NAME}=${session.id}` };
  }

  async function enrollStudent(
    studentId: string,
    subjectId = SUBJECT_SWE_101,
  ): Promise<void> {
    await db.query(
      `INSERT INTO enrollments (student_id, class_id, subject_id) VALUES ($1, $2, $3)`,
      [studentId, CLASS_HESD_01, subjectId],
    );
  }

  async function seedClosedSession(
    instructorId: string,
    closedAt: Date,
    subjectId = SUBJECT_SWE_101,
    status: SessionStatus = SessionStatus.Closed,
  ): Promise<string> {
    const sessionId = crypto.randomUUID();
    await db.query(
      `INSERT INTO sessions
         (id, instructor_id, class_id, subject_id, title, room_name,
          room_latitude, room_longitude, gps_radius_meters, scheduled_start,
          status, opened_at, closed_at)
       VALUES ($1, $2, $3, $4, 'Workshop', 'Room A', $5, $6, 100, $7, $8, $9, $10)`,
      [
        sessionId,
        instructorId,
        CLASS_HESD_01,
        subjectId,
        ROOM_LAT,
        ROOM_LNG,
        closedAt,
        status,
        status === SessionStatus.Closed ? closedAt : null,
        status === SessionStatus.Closed ? closedAt : null,
      ],
    );
    return sessionId;
  }

  async function seedActiveSession(instructorId: string): Promise<string> {
    const sessionId = crypto.randomUUID();
    const start = new Date("2026-06-28T08:00:00.000Z");
    await db.query(
      `INSERT INTO sessions
         (id, instructor_id, class_id, subject_id, title, room_name,
          room_latitude, room_longitude, gps_radius_meters, scheduled_start,
          status, opened_at)
       VALUES ($1, $2, $3, $4, 'Active Workshop', 'Room A', $5, $6, 100, $7, $8, $7)`,
      [
        sessionId,
        instructorId,
        CLASS_HESD_01,
        SUBJECT_SWE_101,
        ROOM_LAT,
        ROOM_LNG,
        start,
        SessionStatus.Active,
      ],
    );
    return sessionId;
  }

  async function seedAttendance(
    sessionId: string,
    studentId: string,
    status: AttendanceStatus,
  ): Promise<void> {
    await db.query(
      `INSERT INTO attendance_records (id, session_id, student_id, status)
       VALUES ($1, $2, $3, $4)`,
      [crypto.randomUUID(), sessionId, studentId, status],
    );
  }

  async function waitForThresholdEvaluation(sessionId: string): Promise<void> {
    await notificationService.evaluateAbsenceThresholds(sessionId);
  }

  it("TC-AC-16-003: evaluateAbsenceThresholds creates student and instructor notifications", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026001", "s1@example.edu.vn", "Student C");
    await enrollStudent(student.userId);

    const base = new Date("2026-06-01T08:00:00.000Z");
    const statuses: AttendanceStatus[] = [
      AttendanceStatus.Present,
      AttendanceStatus.Present,
      AttendanceStatus.Absent,
      AttendanceStatus.Present,
      AttendanceStatus.Present,
    ];
    for (let i = 0; i < 5; i++) {
      const sessionId = await seedClosedSession(
        instructor.userId,
        new Date(base.getTime() + i * 86_400_000),
      );
      await seedAttendance(sessionId, student.userId, statuses[i]!);
    }

    const sixthSession = await seedClosedSession(
      instructor.userId,
      new Date(base.getTime() + 5 * 86_400_000),
    );
    await seedAttendance(sixthSession, student.userId, AttendanceStatus.Absent);

    await waitForThresholdEvaluation(sixthSession);

    const studentRows = await db.query<{ payload: Record<string, unknown> }>(
      `SELECT payload FROM notifications
       WHERE user_id = $1 AND type = $2`,
      [student.userId, NotificationType.AbsenceThresholdWarning],
    );
    assert.equal(studentRows.rowCount, 1);
    const payload = studentRows.rows[0]!.payload;
    assert.equal(payload.subjectCode, "SWE-101");
    assert.equal(payload.unexcusedAbsenceCount, 2);
    assert.equal(payload.sessionCount, 6);
    assert.equal(payload.absenceRate, 2 / 6);
    assert.equal(payload.threshold, 0.2);

    const instructorRows = await db.query(
      `SELECT id FROM notifications
       WHERE user_id = $1 AND type = $2`,
      [instructor.userId, NotificationType.AbsenceThresholdWarning],
    );
    assert.equal(instructorRows.rowCount, 1);
  });

  it("TC-AC-16-004: excused absences excluded from numerator", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026002", "s2@example.edu.vn", "Student D");
    await enrollStudent(student.userId, SUBJECT_TEST_101);

    const base = new Date("2026-06-01T08:00:00.000Z");
    const statuses: AttendanceStatus[] = [
      AttendanceStatus.Absent,
      AttendanceStatus.Excused,
      AttendanceStatus.Present,
      AttendanceStatus.Present,
      AttendanceStatus.Present,
    ];
    for (let i = 0; i < 5; i++) {
      const sessionId = await seedClosedSession(
        instructor.userId,
        new Date(base.getTime() + i * 86_400_000),
        SUBJECT_TEST_101,
      );
      await seedAttendance(sessionId, student.userId, statuses[i]!);
    }

    const sixthSession = await seedClosedSession(
      instructor.userId,
      new Date(base.getTime() + 5 * 86_400_000),
      SUBJECT_TEST_101,
    );
    await seedAttendance(sixthSession, student.userId, AttendanceStatus.Present);

    await waitForThresholdEvaluation(sixthSession);

    const none = await db.query(
      `SELECT id FROM notifications WHERE user_id = $1`,
      [student.userId],
    );
    assert.equal(none.rowCount, 0);

    const seventhSession = await seedClosedSession(
      instructor.userId,
      new Date(base.getTime() + 6 * 86_400_000),
      SUBJECT_TEST_101,
    );
    const recordId = crypto.randomUUID();
    await db.query(
      `INSERT INTO attendance_records (id, session_id, student_id, status)
       VALUES ($1, $2, $3, $4)`,
      [recordId, seventhSession, student.userId, AttendanceStatus.Present],
    );
    await db.query(
      `UPDATE attendance_records SET status = 'Absent' WHERE id = $1`,
      [recordId],
    );
    await waitForThresholdEvaluation(seventhSession);

    const after = await db.query(
      `SELECT id FROM notifications WHERE user_id = $1`,
      [student.userId],
    );
    assert.equal(after.rowCount, 1);
  });

  it("TC-AC-16-005: session close triggers threshold evaluation via API", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026003", "s3@example.edu.vn", "Student E");
    await enrollStudent(student.userId);

    const base = new Date("2026-06-01T08:00:00.000Z");
    for (let i = 0; i < 4; i++) {
      const sessionId = await seedClosedSession(
        instructor.userId,
        new Date(base.getTime() + i * 86_400_000),
      );
      await seedAttendance(
        sessionId,
        student.userId,
        i === 0 ? AttendanceStatus.Absent : AttendanceStatus.Present,
      );
    }

    const activeSession = await seedActiveSession(instructor.userId);
    await seedAttendance(activeSession, student.userId, AttendanceStatus.Pending);

    const before = await app.inject({
      method: "GET",
      url: `/api/v1/sessions/${activeSession}/attendance`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(before.statusCode, 200);
    const beforeBody = before.json() as { summary: { pending: number } };
    assert.ok(beforeBody.summary.pending > 0);

    const closeRes = await app.inject({
      method: "POST",
      url: `/api/v1/sessions/${activeSession}/close`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(closeRes.statusCode, 200);
    const closed = closeRes.json() as { status: string; closedAt: string | null };
    assert.equal(closed.status, SessionStatus.Closed);
    assert.ok(closed.closedAt);

    await waitForThresholdEvaluation(activeSession);

    const after = await app.inject({
      method: "GET",
      url: `/api/v1/sessions/${activeSession}/attendance`,
      headers: { cookie: instructor.cookie },
    });
    const afterBody = after.json() as {
      summary: { pending: number; absent: number };
    };
    assert.equal(afterBody.summary.pending, 0);
    assert.ok(afterBody.summary.absent >= 1);

    const notes = await app.inject({
      method: "GET",
      url: "/api/v1/notifications",
      headers: { cookie: student.cookie },
    });
    const noteBody = notes.json() as { items: Array<{ type: string }> };
    assert.ok(
      noteBody.items.some((n) => n.type === NotificationType.AbsenceThresholdWarning),
    );
  });

  it("TC-AC-16-007: GET /notifications and PATCH read HTTP contract", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026004", "s4@example.edu.vn", "Student G");
    await enrollStudent(student.userId);

    const sessionId = await seedClosedSession(
      instructor.userId,
      new Date("2026-06-28T08:00:00.000Z"),
    );
    for (let i = 0; i < 4; i++) {
      const prior = await seedClosedSession(
        instructor.userId,
        new Date(`2026-06-${String(i + 1).padStart(2, "0")}T08:00:00.000Z`),
      );
      await seedAttendance(
        prior,
        student.userId,
        i === 0 ? AttendanceStatus.Absent : AttendanceStatus.Present,
      );
    }
    await seedAttendance(sessionId, student.userId, AttendanceStatus.Absent);
    await waitForThresholdEvaluation(sessionId);

    const listRes = await app.inject({
      method: "GET",
      url: "/api/v1/notifications",
      headers: { cookie: student.cookie },
    });
    assert.equal(listRes.statusCode, 200);
    assert.match(listRes.headers["content-type"] ?? "", /application\/json/);
    const listBody = listRes.json() as {
      items: Array<{
        id: string;
        type: string;
        payload: Record<string, unknown>;
        readAt: string | null;
        createdAt: string;
      }>;
    };
    assert.ok(listBody.items.length >= 1);
    const item = listBody.items.find(
      (n) => n.type === NotificationType.AbsenceThresholdWarning,
    );
    assert.ok(item);
    assert.equal(item.payload.subjectCode, "SWE-101");
    assert.ok(item.payload.subjectName);
    assert.ok(typeof item.payload.absenceRate === "number");
    assert.equal(item.readAt, null);
    assert.ok(item.createdAt.endsWith("Z"));

    const readRes = await app.inject({
      method: "PATCH",
      url: `/api/v1/notifications/${item!.id}/read`,
      headers: { cookie: student.cookie },
    });
    assert.equal(readRes.statusCode, 204);

    const again = await app.inject({
      method: "GET",
      url: "/api/v1/notifications",
      headers: { cookie: student.cookie },
    });
    const againBody = again.json() as {
      items: Array<{ id: string; readAt: string | null }>;
    };
    const readItem = againBody.items.find((n) => n.id === item!.id);
    assert.ok(readItem?.readAt);
  });

  it("TC-AC-16-008: admin PUT /policy/absence-threshold persists value", async () => {
    await resetDb();
    const admin = await seedAdmin();

    const getRes = await app.inject({
      method: "GET",
      url: "/api/v1/policy/absence-threshold",
      headers: { cookie: admin.cookie },
    });
    assert.equal(getRes.statusCode, 200);
    assert.equal((getRes.json() as { thresholdPercent: number }).thresholdPercent, 20);

    const putRes = await app.inject({
      method: "PUT",
      url: "/api/v1/policy/absence-threshold",
      headers: { cookie: admin.cookie },
      payload: { thresholdPercent: 25 },
    });
    assert.equal(putRes.statusCode, 200);
    assert.equal((putRes.json() as { thresholdPercent: number }).thresholdPercent, 25);

    const verify = await app.inject({
      method: "GET",
      url: "/api/v1/policy/absence-threshold",
      headers: { cookie: admin.cookie },
    });
    assert.equal((verify.json() as { thresholdPercent: number }).thresholdPercent, 25);

    await app.inject({
      method: "PUT",
      url: "/api/v1/policy/absence-threshold",
      headers: { cookie: admin.cookie },
      payload: { thresholdPercent: 20 },
    });
  });

  it("TC-AC-16-009: instructor denied PUT /policy/absence-threshold", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();

    const res = await app.inject({
      method: "PUT",
      url: "/api/v1/policy/absence-threshold",
      headers: { cookie: instructor.cookie },
      payload: { thresholdPercent: 15 },
    });
    assert.equal(res.statusCode, 403);
    const body = res.json() as { errorCode: string; message: string };
    assert.equal(body.errorCode, ErrorCode.Forbidden);

    const policy = await db.query<{ value: string }>(
      "SELECT value FROM policy_settings WHERE key = $1",
      [POLICY_KEY_ABSENCE_THRESHOLD],
    );
    assert.equal(policy.rows[0]?.value, "20");
  });

  it("TC-AC-16-010: student notifications scoped to self only", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const studentH = await seedStudent("SV2026005", "h@example.edu.vn", "Student H");
    const studentI = await seedStudent("SV2026006", "i@example.edu.vn", "Student I");
    await enrollStudent(studentI.userId);

    const sessionId = await seedClosedSession(
      instructor.userId,
      new Date("2026-06-28T08:00:00.000Z"),
    );
    for (let i = 0; i < 4; i++) {
      const prior = await seedClosedSession(
        instructor.userId,
        new Date(`2026-06-0${i + 1}T08:00:00.000Z`),
      );
      await seedAttendance(
        prior,
        studentI.userId,
        i === 0 ? AttendanceStatus.Absent : AttendanceStatus.Present,
      );
    }
    await seedAttendance(sessionId, studentI.userId, AttendanceStatus.Absent);
    await waitForThresholdEvaluation(sessionId);

    const hList = await app.inject({
      method: "GET",
      url: "/api/v1/notifications",
      headers: { cookie: studentH.cookie },
    });
    assert.equal((hList.json() as { items: unknown[] }).items.length, 0);

    const iList = await app.inject({
      method: "GET",
      url: "/api/v1/notifications",
      headers: { cookie: studentI.cookie },
    });
    const iItems = (iList.json() as { items: Array<{ id: string }> }).items;
    assert.equal(iItems.length, 1);

    const denied = await app.inject({
      method: "PATCH",
      url: `/api/v1/notifications/${iItems[0]!.id}/read`,
      headers: { cookie: studentH.cookie },
    });
    assert.equal(denied.statusCode, 403);
  });

  it("TC-AC-16-011: no notification when rate at or below threshold", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026007", "k@example.edu.vn", "Student K");
    await enrollStudent(student.userId);

    const base = new Date("2026-06-01T08:00:00.000Z");
    for (let i = 0; i < 8; i++) {
      const sessionId = await seedClosedSession(
        instructor.userId,
        new Date(base.getTime() + i * 86_400_000),
      );
      await seedAttendance(
        sessionId,
        student.userId,
        i === 0 ? AttendanceStatus.Absent : AttendanceStatus.Present,
      );
    }

    const ninth = await seedClosedSession(
      instructor.userId,
      new Date(base.getTime() + 8 * 86_400_000),
    );
    await seedAttendance(ninth, student.userId, AttendanceStatus.Present);
    await waitForThresholdEvaluation(ninth);

    const rows = await db.query(
      `SELECT id FROM notifications WHERE user_id = $1`,
      [student.userId],
    );
    assert.equal(rows.rowCount, 0);
  });

  it("TC-AC-16-012: invalid threshold returns 422 ValidationFailed", async () => {
    await resetDb();
    const admin = await seedAdmin();

    for (const value of [0, 101]) {
      const res = await app.inject({
        method: "PUT",
        url: "/api/v1/policy/absence-threshold",
        headers: { cookie: admin.cookie },
        payload: { thresholdPercent: value },
      });
      assert.equal(res.statusCode, 422);
      assert.equal((res.json() as { errorCode: string }).errorCode, ErrorCode.ValidationFailed);
    }

    const policy = await db.query<{ value: string }>(
      "SELECT value FROM policy_settings WHERE key = $1",
      [POLICY_KEY_ABSENCE_THRESHOLD],
    );
    assert.equal(policy.rows[0]?.value, "20");
  });

  it("TC-AC-16-018: draft and active sessions excluded from denominator", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026008", "n@example.edu.vn", "Student N");
    await enrollStudent(student.userId);

    const base = new Date("2026-06-01T08:00:00.000Z");
    for (let i = 0; i < 4; i++) {
      const sessionId = await seedClosedSession(
        instructor.userId,
        new Date(base.getTime() + i * 86_400_000),
      );
      await seedAttendance(
        sessionId,
        student.userId,
        i < 2 ? AttendanceStatus.Absent : AttendanceStatus.Present,
      );
    }

    const draftSession = await seedClosedSession(
      instructor.userId,
      new Date(base.getTime() + 4 * 86_400_000),
      SUBJECT_SWE_101,
      SessionStatus.Draft,
    );
    await seedAttendance(draftSession, student.userId, AttendanceStatus.Pending);

    const activeSession = await seedActiveSession(instructor.userId);
    await seedAttendance(activeSession, student.userId, AttendanceStatus.Pending);

    const fifthClosed = await seedClosedSession(
      instructor.userId,
      new Date(base.getTime() + 5 * 86_400_000),
    );
    await seedAttendance(fifthClosed, student.userId, AttendanceStatus.Present);
    await waitForThresholdEvaluation(fifthClosed);

    const stats = await db.query<{ payload: Record<string, unknown> }>(
      `SELECT payload FROM notifications WHERE user_id = $1`,
      [student.userId],
    );
    assert.equal(stats.rowCount, 1);
    assert.equal(stats.rows[0]!.payload.sessionCount, 5);
    assert.equal(stats.rows[0]!.payload.unexcusedAbsenceCount, 2);
    assert.equal(stats.rows[0]!.payload.absenceRate, 0.4);
  });

  it("TC-FR-16-017: custom admin threshold applied during evaluation", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const admin = await seedAdmin();
    const student = await seedStudent("SV2026009", "o@example.edu.vn", "Student O");
    await enrollStudent(student.userId);

    const base = new Date("2026-06-01T08:00:00.000Z");
    for (let i = 0; i < 9; i++) {
      const sessionId = await seedClosedSession(
        instructor.userId,
        new Date(base.getTime() + i * 86_400_000),
      );
      await seedAttendance(
        sessionId,
        student.userId,
        i < 2 ? AttendanceStatus.Absent : AttendanceStatus.Present,
      );
    }

    const tenth = await seedClosedSession(
      instructor.userId,
      new Date(base.getTime() + 9 * 86_400_000),
    );
    await seedAttendance(tenth, student.userId, AttendanceStatus.Present);

    await app.inject({
      method: "PUT",
      url: "/api/v1/policy/absence-threshold",
      headers: { cookie: admin.cookie },
      payload: { thresholdPercent: 25 },
    });

    await waitForThresholdEvaluation(tenth);
    let rows = await db.query(
      `SELECT id FROM notifications WHERE user_id = $1`,
      [student.userId],
    );
    assert.equal(rows.rowCount, 0);

    await app.inject({
      method: "PUT",
      url: "/api/v1/policy/absence-threshold",
      headers: { cookie: admin.cookie },
      payload: { thresholdPercent: 15 },
    });

    await waitForThresholdEvaluation(tenth);
    rows = await db.query(
      `SELECT id FROM notifications WHERE user_id = $1`,
      [student.userId],
    );
    assert.equal(rows.rowCount, 1);
  });

  it("TC-FR-16-019: parallel evaluation does not duplicate notifications", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026010", "q@example.edu.vn", "Student Q");
    await enrollStudent(student.userId);

    const base = new Date("2026-06-01T08:00:00.000Z");
    for (let i = 0; i < 4; i++) {
      const sessionId = await seedClosedSession(
        instructor.userId,
        new Date(base.getTime() + i * 86_400_000),
      );
      await seedAttendance(
        sessionId,
        student.userId,
        i === 0 ? AttendanceStatus.Absent : AttendanceStatus.Present,
      );
    }

    const trigger = await seedClosedSession(
      instructor.userId,
      new Date(base.getTime() + 4 * 86_400_000),
    );
    await seedAttendance(trigger, student.userId, AttendanceStatus.Absent);

    await Promise.all([
      notificationService.evaluateAbsenceThresholds(trigger),
      notificationService.evaluateAbsenceThresholds(trigger),
    ]);

    const studentCount = await db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM notifications
       WHERE user_id = $1 AND type = $2`,
      [student.userId, NotificationType.AbsenceThresholdWarning],
    );
    assert.equal(studentCount.rows[0]?.count, "1");

    const instructorCount = await db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM notifications
       WHERE user_id = $1 AND type = $2`,
      [instructor.userId, NotificationType.AbsenceThresholdWarning],
    );
    assert.equal(instructorCount.rows[0]?.count, "1");

    await notificationService.evaluateAbsenceThresholds(trigger);
    const again = await db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM notifications WHERE user_id = $1`,
      [student.userId],
    );
    assert.equal(again.rows[0]?.count, "1");
  });

  it("TC-FR-16-020: unauthenticated GET /notifications returns 401", async () => {
    await resetDb();
    const res = await app.inject({
      method: "GET",
      url: "/api/v1/notifications",
    });
    assert.equal(res.statusCode, 401);
    assert.equal((res.json() as { errorCode: string }).errorCode, ErrorCode.Unauthenticated);
  });
});
