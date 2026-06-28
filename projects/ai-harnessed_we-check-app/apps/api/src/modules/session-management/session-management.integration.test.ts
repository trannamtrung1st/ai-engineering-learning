import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import {
  AttendanceStatus,
  ErrorCode,
  QrTokenStatus,
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
import { resetClock, setClock, now } from "../../infra/clock.js";
import { truncateRosterTables } from "../roster-enrollment/roster-service.js";
import { AutoCloseScheduler } from "./auto-close-scheduler.js";
import {
  SessionService,
  truncateSessionTables,
} from "./session-service.js";
import { ApiError } from "../../errors/api-error.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

const CLASS_HESD_01 = "10000000-0000-4000-8000-000000000101";
const CLASS_HESD_02 = "10000000-0000-4000-8000-000000000102";
const SUBJECT_SWE_101 = "20000000-0000-4000-8000-000000000201";

const ROOM_LAT = 10.762622;
const ROOM_LNG = 106.660172;

/**
 * Traceability: AC-04 AC-05 FR-04 FR-05 BR-01 BR-07 NFR-01 NFR-22
 * Integration cases: TC-AC-04-002 TC-AC-04-005 TC-AC-04-007 TC-AC-04-013 TC-AC-04-019
 * TC-AC-05-002 TC-AC-05-007 TC-AC-05-008 TC-AC-05-009 TC-AC-05-016 TC-AC-05-021
 * TC-BR-07-003 TC-BR-07-004 TC-BR-07-011 TC-BR-07-020 TC-FR-04-002 TC-FR-04-005
 * TC-FR-04-007 TC-FR-04-026 TC-FR-04-028 TC-FR-05-002 TC-FR-05-007 TC-FR-05-008
 * TC-FR-05-009 TC-FR-05-016 TC-FR-05-021 TC-FR-05-024 TC-NFR-01-001
 * E2E cases: TC-NFR-01-003 TC-NFR-01-010
 */
describe("session-management integration (AC-04, AC-05, FR-04, FR-05, BR-01, BR-07, NFR-01)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let store: SessionStore;
  let sessionService: SessionService;
  let autoClose: AutoCloseScheduler;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    store = new SessionStore(db);
    sessionService = new SessionService(db);
    autoClose = new AutoCloseScheduler(db, sessionService);
  });

  after(async () => {
    sessionService.qr.stopAll();
    resetClock();
    await app.close();
    await closePool();
  });

  async function resetDb(): Promise<void> {
    sessionService.qr.stopAll();
    await truncateSessionTables(db);
    await truncateRosterTables(db);
    await truncateAuthTables(db);
    resetClock();
  }

  async function seedReferenceData(): Promise<void> {
    await db.query(
      `INSERT INTO classes (id, code, name) VALUES
       ($1, 'HESD-01', 'HESD Cohort A'),
       ($2, 'HESD-02', 'HESD Cohort B')`,
      [CLASS_HESD_01, CLASS_HESD_02],
    );
    await db.query(
      `INSERT INTO subjects (id, code, name) VALUES ($1, 'SWE-101', 'Software Engineering 101')`,
      [SUBJECT_SWE_101],
    );
  }

  async function seedInstructor(
    assignedToHesd01 = true,
  ): Promise<{ userId: string; cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId: "GV2026001",
      displayName: "Instructor One",
      email: "instructor@example.edu.vn",
      role: UserRole.Instructor,
    });
    if (assignedToHesd01) {
      await db.query(
        `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
         VALUES ($1, $2, $3)`,
        [userId, CLASS_HESD_01, SUBJECT_SWE_101],
      );
    }
    const session = await store.createSession(userId);
    return { userId, cookie: `${SESSION_COOKIE_NAME}=${session.id}` };
  }

  async function seedStudent(): Promise<{ userId: string; cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId: "SV2026001",
      displayName: "Student One",
      email: "student@example.edu.vn",
      role: UserRole.Student,
    });
    const session = await store.createSession(userId);
    return { userId, cookie: `${SESSION_COOKIE_NAME}=${session.id}` };
  }

  async function seedAdmin(): Promise<{ cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId: "ADMIN001",
      displayName: "Admin User",
      email: "admin@example.edu.vn",
      role: UserRole.TrainingOfficeAdmin,
    });
    const session = await store.createSession(userId);
    return { cookie: `${SESSION_COOKIE_NAME}=${session.id}` };
  }

  async function seedEnrollment(studentId: string): Promise<void> {
    await db.query(
      `INSERT INTO enrollments (student_id, class_id, subject_id)
       VALUES ($1, $2, $3)`,
      [studentId, CLASS_HESD_01, SUBJECT_SWE_101],
    );
  }

  function futureStart(): string {
    return new Date(now().getTime() + 60 * 60 * 1000).toISOString();
  }

  async function assertHealthOk(): Promise<void> {
    const response = await app.inject({ method: "GET", url: "/api/v1/health" });
    assert.equal(response.statusCode, 200);
    const body = response.json<{ status: string; db: string }>();
    assert.equal(body.status, "ok");
    assert.equal(body.db, "connected");
  }

  async function seedActiveSessionWithEnrollment(): Promise<{
    sessionId: string;
    instructor: { userId: string; cookie: string };
    student: { userId: string; cookie: string };
  }> {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();
    const student = await seedStudent();
    await seedEnrollment(student.userId);

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    await sessionService.open(created.id, instructor.userId, UserRole.Instructor);

    return { sessionId: created.id, instructor, student };
  }

  it("SessionService.create persists Draft session with GPS (TC-AC-04-002, TC-FR-04-002, FR-04)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        gpsRadiusMeters: 100,
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    const row = await db.query<{
      status: string;
      room_latitude: number;
      room_longitude: number;
      gps_radius_meters: number;
    }>(
      `SELECT status, room_latitude, room_longitude, gps_radius_meters
       FROM sessions WHERE id = $1`,
      [created.id],
    );

    assert.equal(row.rows[0]?.status, SessionStatus.Draft);
    assert.equal(row.rows[0]?.room_latitude, ROOM_LAT);
    assert.equal(row.rows[0]?.gps_radius_meters, 100);

    const attendanceCount = await db.query(
      `SELECT COUNT(*)::int AS count FROM attendance_records WHERE session_id = $1`,
      [created.id],
    );
    assert.equal(attendanceCount.rows[0]?.count, 0);
  });

  it("default gpsRadiusMeters is 100 when omitted (TC-FR-04-028)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    const row = await db.query<{ gps_radius_meters: number }>(
      `SELECT gps_radius_meters FROM sessions WHERE id = $1`,
      [created.id],
    );
    assert.equal(row.rows[0]?.gps_radius_meters, 100);
  });

  it("SessionService.open rejects missing GPS and preserves Draft (TC-AC-04-005, TC-BR-07-003, BR-07)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    await assert.rejects(
      () => sessionService.open(created.id, instructor.userId, UserRole.Instructor),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.errorCode, ErrorCode.RoomGpsRequired);
        return true;
      },
    );

    const row = await db.query<{ status: string; opened_at: Date | null }>(
      `SELECT status, opened_at FROM sessions WHERE id = $1`,
      [created.id],
    );
    assert.equal(row.rows[0]?.status, SessionStatus.Draft);
    assert.equal(row.rows[0]?.opened_at, null);
  });

  it("parallel open without GPS both reject (TC-AC-04-019, TC-BR-07-020)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    const results = await Promise.allSettled([
      sessionService.open(created.id, instructor.userId, UserRole.Instructor),
      sessionService.open(created.id, instructor.userId, UserRole.Instructor),
    ]);

    assert.equal(results[0]?.status, "rejected");
    assert.equal(results[1]?.status, "rejected");

    const row = await db.query<{ status: string; opened_at: Date | null }>(
      `SELECT status, opened_at FROM sessions WHERE id = $1`,
      [created.id],
    );
    assert.equal(row.rows[0]?.status, SessionStatus.Draft);
    assert.equal(row.rows[0]?.opened_at, null);
  });

  it("SessionService.cancel transitions Draft to Cancelled (TC-AC-04-007, FR-04)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    const cancelled = await sessionService.cancel(
      created.id,
      instructor.userId,
      UserRole.Instructor,
    );
    assert.equal(cancelled.status, SessionStatus.Cancelled);

    const attendanceCount = await db.query(
      `SELECT COUNT(*)::int AS count FROM attendance_records WHERE session_id = $1`,
      [created.id],
    );
    assert.equal(attendanceCount.rows[0]?.count, 0);
  });

  it("SessionService.cancel rejects Active session (TC-FR-04-026)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();
    const student = await seedStudent();
    await seedEnrollment(student.userId);

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    await sessionService.open(created.id, instructor.userId, UserRole.Instructor);

    await assert.rejects(
      () => sessionService.cancel(created.id, instructor.userId, UserRole.Instructor),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.errorCode, ErrorCode.InvalidSessionState);
        return true;
      },
    );
  });

  it("open seeds Pending attendance equal to enrollment count (TC-AC-05-002, TC-FR-05-002, FR-05)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();
    const student = await seedStudent();
    await seedEnrollment(student.userId);

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    const opened = await sessionService.open(
      created.id,
      instructor.userId,
      UserRole.Instructor,
    );
    assert.equal(opened.status, SessionStatus.Active);
    assert.ok(opened.openedAt);

    const records = await db.query<{ status: string; checked_in_at: Date | null }>(
      `SELECT status, checked_in_at FROM attendance_records WHERE session_id = $1`,
      [created.id],
    );
    assert.equal(records.rowCount, 1);
    assert.equal(records.rows[0]?.status, AttendanceStatus.Pending);
    assert.equal(records.rows[0]?.checked_in_at, null);

    const qrCount = await db.query(
      `SELECT COUNT(*)::int AS count FROM qr_tokens WHERE session_id = $1`,
      [created.id],
    );
    assert.ok((qrCount.rows[0]?.count ?? 0) >= 1);
  });

  it("close bulk updates Pending to Absent preserving Present (TC-AC-05-008, TC-FR-05-008, BR-01)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();
    const student = await seedStudent();
    await seedEnrollment(student.userId);

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    await sessionService.open(created.id, instructor.userId, UserRole.Instructor);

    const record = await db.query<{ id: string }>(
      `SELECT id FROM attendance_records WHERE session_id = $1`,
      [created.id],
    );
    const recordId = record.rows[0]!.id;

    await db.query(
      `UPDATE attendance_records SET status = $2, checked_in_at = NOW()
       WHERE id = $1`,
      [recordId, AttendanceStatus.Present],
    );

    const closed = await sessionService.close(
      created.id,
      instructor.userId,
      UserRole.Instructor,
    );
    assert.equal(closed.status, SessionStatus.Closed);
    assert.ok(closed.closedAt);

    const final = await db.query<{ status: string }>(
      `SELECT status FROM attendance_records WHERE id = $1`,
      [recordId],
    );
    assert.equal(final.rows[0]?.status, AttendanceStatus.Present);
  });

  it("AutoCloseScheduler closes session at scheduledStart + 10 min (TC-AC-05-009, TC-BR-01-005, BR-01)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();
    const student = await seedStudent();
    await seedEnrollment(student.userId);

    const scheduledStart = "2026-06-01T09:00:00.000Z";
    setClock("2026-06-01T09:00:00.000Z");

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart,
      },
      instructor.userId,
      UserRole.Instructor,
    );

    await sessionService.open(created.id, instructor.userId, UserRole.Instructor);

    setClock("2026-06-01T09:10:00.000Z");
    const closedCount = await autoClose.run();
    assert.equal(closedCount, 1);

    const row = await db.query<{ status: string; closed_at: Date | null }>(
      `SELECT status, closed_at FROM sessions WHERE id = $1`,
      [created.id],
    );
    assert.equal(row.rows[0]?.status, SessionStatus.Closed);
    assert.ok(row.rows[0]?.closed_at);

    const absentCount = await db.query<{ count: number }>(
      `SELECT COUNT(*)::int AS count FROM attendance_records
       WHERE session_id = $1 AND status = $2`,
      [created.id, AttendanceStatus.Absent],
    );
    assert.equal(absentCount.rows[0]?.count, 1);
  });

  it("close rejects non-Active session (TC-AC-05-016, TC-FR-05-016)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    await assert.rejects(
      () => sessionService.close(created.id, instructor.userId, UserRole.Instructor),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.errorCode, ErrorCode.InvalidSessionState);
        return true;
      },
    );
  });

  it("POST /sessions returns 201 Draft with GPS (TC-AC-04-003, AC-04)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/sessions",
      headers: { cookie: instructor.cookie },
      payload: {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        gpsRadiusMeters: 100,
        scheduledStart: futureStart(),
      },
    });

    assert.equal(response.statusCode, 201);
    const body = response.json<{
      status: string;
      roomLatitude: number;
      openedAt: string | null;
      closedAt: string | null;
    }>();
    assert.equal(body.status, SessionStatus.Draft);
    assert.equal(body.roomLatitude, ROOM_LAT);
    assert.equal(body.openedAt, null);
    assert.equal(body.closedAt, null);
  });

  it("open without GPS returns 422 RoomGpsRequired (TC-AC-04-004, TC-BR-07-007)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();

    const createResponse = await app.inject({
      method: "POST",
      url: "/api/v1/sessions",
      headers: { cookie: instructor.cookie },
      payload: {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        scheduledStart: futureStart(),
      },
    });
    const { id } = createResponse.json<{ id: string }>();

    const openResponse = await app.inject({
      method: "POST",
      url: `/api/v1/sessions/${id}/open`,
      headers: { cookie: instructor.cookie },
    });

    assert.equal(openResponse.statusCode, 422);
    const body = openResponse.json<{ errorCode: string }>();
    assert.equal(body.errorCode, ErrorCode.RoomGpsRequired);
  });

  it("Student denied POST /sessions with 403 (TC-AC-04-009)", async () => {
    await resetDb();
    await seedReferenceData();
    const student = await seedStudent();

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/sessions",
      headers: { cookie: student.cookie },
      payload: {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        scheduledStart: futureStart(),
      },
    });

    assert.equal(response.statusCode, 403);
    assert.equal(response.json<{ errorCode: string }>().errorCode, ErrorCode.Forbidden);
  });

  it("Admin denied POST /sessions with 403 (TC-AC-04-010)", async () => {
    await resetDb();
    await seedReferenceData();
    const admin = await seedAdmin();

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/sessions",
      headers: { cookie: admin.cookie },
      payload: {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        scheduledStart: futureStart(),
      },
    });

    assert.equal(response.statusCode, 403);
  });

  it("instructor denied unassigned class with 403 (TC-AC-04-011)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor(true);

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/sessions",
      headers: { cookie: instructor.cookie },
      payload: {
        classId: CLASS_HESD_02,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        scheduledStart: futureStart(),
      },
    });

    assert.equal(response.statusCode, 403);
  });

  it("PATCH Draft GPS then open succeeds (TC-AC-04-020, TC-BR-07-019, WF-02)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();
    const student = await seedStudent();
    await seedEnrollment(student.userId);

    const createResponse = await app.inject({
      method: "POST",
      url: "/api/v1/sessions",
      headers: { cookie: instructor.cookie },
      payload: {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        scheduledStart: futureStart(),
      },
    });
    const { id } = createResponse.json<{ id: string; status: string }>();
    assert.equal(createResponse.json<{ status: string }>().status, SessionStatus.Draft);

    const patchResponse = await app.inject({
      method: "PATCH",
      url: `/api/v1/sessions/${id}`,
      headers: { cookie: instructor.cookie },
      payload: {
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
      },
    });
    assert.equal(patchResponse.statusCode, 200);

    const openResponse = await app.inject({
      method: "POST",
      url: `/api/v1/sessions/${id}/open`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(openResponse.statusCode, 200);
    assert.equal(
      openResponse.json<{ status: string }>().status,
      SessionStatus.Active,
    );
  });

  it("open on Active session returns 409 InvalidSessionState (TC-AC-05-014)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();

    const createResponse = await app.inject({
      method: "POST",
      url: "/api/v1/sessions",
      headers: { cookie: instructor.cookie },
      payload: {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: futureStart(),
      },
    });
    const { id } = createResponse.json<{ id: string }>();

    await app.inject({
      method: "POST",
      url: `/api/v1/sessions/${id}/open`,
      headers: { cookie: instructor.cookie },
    });

    const secondOpen = await app.inject({
      method: "POST",
      url: `/api/v1/sessions/${id}/open`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(secondOpen.statusCode, 409);
    assert.equal(
      secondOpen.json<{ errorCode: string }>().errorCode,
      ErrorCode.InvalidSessionState,
    );
  });

  it("GET qr/current returns valid token while Active (TC-AC-05-001, FR-06)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();

    const createResponse = await app.inject({
      method: "POST",
      url: "/api/v1/sessions",
      headers: { cookie: instructor.cookie },
      payload: {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: futureStart(),
      },
    });
    const { id } = createResponse.json<{ id: string }>();

    await app.inject({
      method: "POST",
      url: `/api/v1/sessions/${id}/open`,
      headers: { cookie: instructor.cookie },
    });

    const qrResponse = await app.inject({
      method: "GET",
      url: `/api/v1/sessions/${id}/qr/current`,
      headers: { cookie: instructor.cookie },
    });

    assert.equal(qrResponse.statusCode, 200);
    const qr = qrResponse.json<{
      qrPayload: string;
      secondsRemaining: number;
      tokenId: string;
    }>();
    assert.ok(qr.qrPayload.includes("wecheck://check-in"));
    assert.ok(qr.secondsRemaining <= 30);

    const tokenRow = await db.query<{ status: string }>(
      `SELECT status FROM qr_tokens WHERE id = $1`,
      [qr.tokenId],
    );
    assert.equal(tokenRow.rows[0]?.status, QrTokenStatus.Valid);
  });

  it("Active session stays consistent during check-in lifecycle (TC-NFR-01-001, NFR-01)", async () => {
    await resetDb();
    await seedReferenceData();
    const instructor = await seedInstructor();
    const student = await seedStudent();
    await seedEnrollment(student.userId);

    const created = await sessionService.create(
      {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Buổi 3",
        roomName: "Phòng A201",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: futureStart(),
      },
      instructor.userId,
      UserRole.Instructor,
    );

    await sessionService.open(created.id, instructor.userId, UserRole.Instructor);

    const activeRow = await db.query<{ status: string; closed_at: Date | null }>(
      `SELECT status, closed_at FROM sessions WHERE id = $1`,
      [created.id],
    );
    assert.equal(activeRow.rows[0]?.status, SessionStatus.Active);
    assert.equal(activeRow.rows[0]?.closed_at, null);

    const pendingCount = await db.query<{ count: number }>(
      `SELECT COUNT(*)::int AS count FROM attendance_records
       WHERE session_id = $1 AND status = $2`,
      [created.id, AttendanceStatus.Pending],
    );
    assert.equal(pendingCount.rows[0]?.count, 1);

    await db.query(
      `UPDATE attendance_records SET status = $2, checked_in_at = NOW()
       WHERE session_id = $1`,
      [created.id, AttendanceStatus.Present],
    );

    const afterCheckIn = await db.query<{ status: string }>(
      `SELECT status FROM sessions WHERE id = $1`,
      [created.id],
    );
    assert.equal(afterCheckIn.rows[0]?.status, SessionStatus.Active);

    const presentCount = await db.query<{ count: number }>(
      `SELECT COUNT(*)::int AS count FROM attendance_records
       WHERE session_id = $1 AND status = $2`,
      [created.id, AttendanceStatus.Present],
    );
    assert.equal(presentCount.rows[0]?.count, 1);
  });

  it("GET /api/v1/health stays ok with db connected during Active session window (TC-NFR-01-003, NFR-01, NFR-22, FR-05)", async () => {
    await seedActiveSessionWithEnrollment();

    const pollCount = 12;
    for (let i = 0; i < pollCount; i += 1) {
      await assertHealthOk();
      if (i < pollCount - 1) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
    }
  });

  it("db disconnect surfaces 503 health; recovery preserves Active session (TC-NFR-01-010, NFR-01, NFR-22, FR-05)", async () => {
    const { sessionId } = await seedActiveSessionWithEnrollment();

    await assertHealthOk();

    const deadPool = createPool(DEFAULT_DATABASE_URL);
    await deadPool.end();
    const degradedApp = await buildApp({ db: deadPool, logger: false });

    const degradedHealth = await degradedApp.inject({
      method: "GET",
      url: "/api/v1/health",
    });
    assert.equal(degradedHealth.statusCode, 503);
    const degradedBody = degradedHealth.json<{ status: string; db: string }>();
    assert.equal(degradedBody.status, "degraded");
    assert.equal(degradedBody.db, "disconnected");
    await degradedApp.close();

    const pendingBefore = await db.query<{ count: number }>(
      `SELECT COUNT(*)::int AS count FROM attendance_records
       WHERE session_id = $1 AND status = $2`,
      [sessionId, AttendanceStatus.Pending],
    );
    assert.equal(pendingBefore.rows[0]?.count, 1);

    const presentBefore = await db.query<{ count: number }>(
      `SELECT COUNT(*)::int AS count FROM attendance_records
       WHERE session_id = $1 AND status = $2`,
      [sessionId, AttendanceStatus.Present],
    );
    assert.equal(presentBefore.rows[0]?.count, 0);

    await assertHealthOk();

    const sessionRow = await db.query<{ status: string }>(
      `SELECT status FROM sessions WHERE id = $1`,
      [sessionId],
    );
    assert.equal(sessionRow.rows[0]?.status, SessionStatus.Active);

    await db.query(
      `UPDATE attendance_records SET status = $2, checked_in_at = NOW()
       WHERE session_id = $1 AND status = $3`,
      [sessionId, AttendanceStatus.Present, AttendanceStatus.Pending],
    );

    const presentAfter = await db.query<{ count: number }>(
      `SELECT COUNT(*)::int AS count FROM attendance_records
       WHERE session_id = $1 AND status = $2`,
      [sessionId, AttendanceStatus.Present],
    );
    assert.equal(presentAfter.rows[0]?.count, 1);
  });
});
