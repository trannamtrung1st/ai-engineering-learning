import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import {
  AttendanceStatus,
  ErrorCode,
  INSTRUCTOR_EDIT_WINDOW_MS,
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
import { resetClock, setClock, advanceClock } from "../../infra/clock.js";
import { truncateRosterTables } from "../roster-enrollment/roster-service.js";
import { truncateSessionTables } from "../session-management/session-service.js";
import { AttendanceService } from "./attendance-service.js";
import { AuditRepository } from "./audit-repository.js";
import { ApiError } from "../../errors/api-error.js";
import { withIntegrationTestDbReset } from "../../infra/integration-test-lock.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

const CLASS_HESD_01 = "10000000-0000-4000-8000-000000000101";
const SUBJECT_SWE_101 = "20000000-0000-4000-8000-000000000201";
const SUBJECT_SWE_102 = "20000000-0000-4000-8000-000000000202";

const ROOM_LAT = 10.762622;
const ROOM_LNG = 106.660172;

/**
 * Traceability: AC-10 AC-11 AC-14 FR-11 FR-14 BR-10 NFR-15
 * Integration: TC-AC-11-003 TC-AC-11-004 TC-AC-11-014 TC-AC-11-016
 * TC-AC-14-002 TC-AC-14-004 TC-FR-11-003 TC-FR-11-004 TC-FR-11-014 TC-FR-11-016
 * TC-FR-11-017 TC-FR-14-002 TC-FR-14-004 TC-BR-10-003 TC-BR-10-004 TC-BR-10-014
 * TC-BR-10-016 TC-BR-10-017 TC-NFR-15-001 TC-NFR-15-004 TC-NFR-15-005 TC-NFR-15-014
 * TC-NFR-15-017 TC-NFR-15-009
 */
describe("attendance integration (AC-10, AC-11, AC-14, FR-11, FR-14, BR-10, NFR-15)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let store: SessionStore;
  let attendanceService: AttendanceService;
  let auditRepo: AuditRepository;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    store = new SessionStore(db);
    attendanceService = new AttendanceService(db);
    auditRepo = new AuditRepository(db);
  });

  after(async () => {
    resetClock();
    await app.close();
    await closePool();
  });

  async function resetDb(afterTruncate?: () => Promise<void>): Promise<void> {
    await withIntegrationTestDbReset(db, async () => {
      await truncateSessionTables(db);
      await truncateRosterTables(db);
      await truncateAuthTables(db);
      resetClock();
      if (afterTruncate) await afterTruncate();
    });
  }

  async function seedReferenceData(): Promise<void> {
    await db.query(
      `INSERT INTO classes (id, code, name) VALUES ($1, 'HESD-01', 'HESD Cohort A')
       ON CONFLICT (id) DO NOTHING`,
      [CLASS_HESD_01],
    );
    await db.query(
      `INSERT INTO subjects (id, code, name) VALUES
       ($1, 'SWE-101', 'Software Engineering 101'),
       ($2, 'SWE-102', 'Software Engineering 102')
       ON CONFLICT (id) DO NOTHING`,
      [SUBJECT_SWE_101, SUBJECT_SWE_102],
    );
  }

  async function seedInstructor(
    email = "instructor@example.edu.vn",
  ): Promise<{ userId: string; cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId: "GV2026001",
      displayName: "Instructor One",
      email,
      role: UserRole.Instructor,
    });
    await db.query(
      `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
       VALUES ($1, $2, $3)`,
      [userId, CLASS_HESD_01, SUBJECT_SWE_101],
    );
    const session = await store.createSession(userId);
    return { userId, cookie: `${SESSION_COOKIE_NAME}=${session.id}` };
  }

  async function seedUnassignedInstructor(): Promise<{ cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId: "GV2026002",
      displayName: "Instructor Two",
      email: "instructor2@example.edu.vn",
      role: UserRole.Instructor,
    });
    const session = await store.createSession(userId);
    return { cookie: `${SESSION_COOKIE_NAME}=${session.id}` };
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

  async function seedClosedSession(
    instructorId: string,
    closedAt: Date,
    subjectId = SUBJECT_SWE_101,
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
        SessionStatus.Closed,
        closedAt,
        closedAt,
      ],
    );
    return sessionId;
  }

  async function seedAttendanceRecord(
    sessionId: string,
    studentId: string,
    status: AttendanceStatus,
  ): Promise<string> {
    const recordId = crypto.randomUUID();
    await db.query(
      `INSERT INTO attendance_records (id, session_id, student_id, status)
       VALUES ($1, $2, $3, $4)`,
      [recordId, sessionId, studentId, status],
    );
    return recordId;
  }

  it("TC-AC-11-003: manualEdit persists status change and audit log (NFR-15)", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026001", "s1@example.edu.vn", "Student One");
    await db.query(
      `INSERT INTO enrollments (student_id, class_id, subject_id) VALUES ($1, $2, $3)`,
      [student.userId, CLASS_HESD_01, SUBJECT_SWE_101],
    );

    const closedAt = new Date("2026-06-28T10:00:00.000Z");
    setClock(new Date(closedAt.getTime() + 2 * 60 * 60 * 1000));
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    const recordId = await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Absent,
    );

    const updated = await attendanceService.manualEdit(
      recordId,
      { status: AttendanceStatus.Present, note: "Xác minh trực tiếp tại lớp" },
      instructor.userId,
      UserRole.Instructor,
    );

    assert.equal(updated.status, AttendanceStatus.Present);
    const row = await db.query<{ status: string }>(
      `SELECT status FROM attendance_records WHERE id = $1`,
      [recordId],
    );
    assert.equal(row.rows[0]?.status, AttendanceStatus.Present);

    const audit = await auditRepo.findLatestForRecord(recordId);
    assert.ok(audit);
    assert.equal(audit.editorId, instructor.userId);
    assert.equal(audit.previousStatus, AttendanceStatus.Absent);
    assert.equal(audit.newStatus, AttendanceStatus.Present);
    assert.equal(audit.note, "Xác minh trực tiếp tại lớp");
  });

  it("TC-AC-11-004: manual edit transitions Absent to Present on Closed session", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026002", "s2@example.edu.vn", "Student Two");
    const closedAt = new Date("2026-06-28T08:00:00.000Z");
    setClock(new Date(closedAt.getTime() + 60 * 60 * 1000));
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    const recordId = await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Absent,
    );

    await attendanceService.manualEdit(
      recordId,
      { status: AttendanceStatus.Present },
      instructor.userId,
      UserRole.Instructor,
    );

    const row = await db.query<{ status: string; checked_in_at: Date | null }>(
      `SELECT status, checked_in_at FROM attendance_records WHERE id = $1`,
      [recordId],
    );
    assert.equal(row.rows[0]?.status, AttendanceStatus.Present);
    assert.ok(row.rows[0]?.checked_in_at);
  });

  it("TC-AC-11-014: EditWindowPolicy denies instructor after 24 h; admin succeeds", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const admin = await seedAdmin();
    const student = await seedStudent("SV2026003", "s3@example.edu.vn", "Student Three");
    const closedAt = new Date("2026-06-28T08:00:00.000Z");
    setClock(new Date(closedAt.getTime() + INSTRUCTOR_EDIT_WINDOW_MS + 60_000));
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    const recordId = await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Absent,
    );

    await assert.rejects(
      () =>
        attendanceService.manualEdit(
          recordId,
          { status: AttendanceStatus.Present },
          instructor.userId,
          UserRole.Instructor,
        ),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.errorCode, ErrorCode.EditWindowExpired);
        return true;
      },
    );

    const adminUpdated = await attendanceService.manualEdit(
      recordId,
      { status: AttendanceStatus.Excused, note: "Admin correction" },
      admin.userId,
      UserRole.TrainingOfficeAdmin,
    );
    assert.equal(adminUpdated.status, AttendanceStatus.Excused);
  });

  it("TC-AC-11-016: manual edit on Active session transitions Pending to Present", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026004", "s4@example.edu.vn", "Student Four");
    const sessionId = crypto.randomUUID();
    const openedAt = new Date("2026-06-28T08:00:00.000Z");
    setClock(openedAt);
    await db.query(
      `INSERT INTO sessions
         (id, instructor_id, class_id, subject_id, title, room_name,
          room_latitude, room_longitude, gps_radius_meters, scheduled_start,
          status, opened_at)
       VALUES ($1, $2, $3, $4, 'Live', 'Room B', $5, $6, 100, $7, $8, $7)`,
      [
        sessionId,
        instructor.userId,
        CLASS_HESD_01,
        SUBJECT_SWE_101,
        ROOM_LAT,
        ROOM_LNG,
        openedAt,
        SessionStatus.Active,
      ],
    );
    const recordId = await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Pending,
    );

    await attendanceService.manualEdit(
      recordId,
      { status: AttendanceStatus.Present, note: "Manual during session" },
      instructor.userId,
      UserRole.Instructor,
    );

    const audit = await auditRepo.findLatestForRecord(recordId);
    assert.equal(audit?.previousStatus, AttendanceStatus.Pending);
    assert.equal(audit?.newStatus, AttendanceStatus.Present);
  });

  it("TC-FR-11-017: manual edit supports all allowed target statuses", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026005", "s5@example.edu.vn", "Student Five");
    const closedAt = new Date("2026-06-28T09:00:00.000Z");
    setClock(new Date(closedAt.getTime() + 60 * 60 * 1000));
    const sessionId = await seedClosedSession(instructor.userId, closedAt);

    const presentId = await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Present,
    );
    await db.query(
      `UPDATE attendance_records SET checked_in_at = NOW() WHERE id = $1`,
      [presentId],
    );

    const student2 = await seedStudent("SV2026006", "s6@example.edu.vn", "Student Six");
    const absentId = await seedAttendanceRecord(
      sessionId,
      student2.userId,
      AttendanceStatus.Absent,
    );

    const student3 = await seedStudent("SV2026007", "s7@example.edu.vn", "Student Seven");
    const excusedId = await seedAttendanceRecord(
      sessionId,
      student3.userId,
      AttendanceStatus.Excused,
    );

    const student4 = await seedStudent("SV2026008", "s8@example.edu.vn", "Student Eight");
    const rejectedId = await seedAttendanceRecord(
      sessionId,
      student4.userId,
      AttendanceStatus.Rejected,
    );

    await attendanceService.manualEdit(
      presentId,
      { status: AttendanceStatus.Excused, note: "Excused" },
      instructor.userId,
      UserRole.Instructor,
    );
    await attendanceService.manualEdit(
      absentId,
      { status: AttendanceStatus.Rejected, note: "Rejected" },
      instructor.userId,
      UserRole.Instructor,
    );
    await attendanceService.manualEdit(
      excusedId,
      { status: AttendanceStatus.Present, note: "Present" },
      instructor.userId,
      UserRole.Instructor,
    );
    await attendanceService.manualEdit(
      rejectedId,
      { status: AttendanceStatus.Absent, note: "Absent" },
      instructor.userId,
      UserRole.Instructor,
    );

    assert.equal(await auditRepo.countForRecord(presentId), 1);
    assert.equal(await auditRepo.countForRecord(absentId), 1);
    assert.equal(await auditRepo.countForRecord(excusedId), 1);
    assert.equal(await auditRepo.countForRecord(rejectedId), 1);
  });

  it("TC-AC-14-002: getStudentHistory returns only self-scoped records", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const studentA = await seedStudent("SV2026101", "a@example.edu.vn", "Student A");
    const studentB = await seedStudent("SV2026102", "b@example.edu.vn", "Student B");
    await db.query(
      `INSERT INTO enrollments (student_id, class_id, subject_id) VALUES ($1, $2, $3), ($4, $2, $3)`,
      [studentA.userId, CLASS_HESD_01, SUBJECT_SWE_101, studentB.userId],
    );

    const closedAt = new Date("2026-06-15T08:00:00.000Z");
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    await seedAttendanceRecord(sessionId, studentA.userId, AttendanceStatus.Present);
    await seedAttendanceRecord(sessionId, studentB.userId, AttendanceStatus.Absent);

    const page = await attendanceService.getStudentHistory(studentA.userId, {
      limit: 20,
    });

    assert.equal(page.totalCount, 1);
    assert.equal(page.items.length, 1);
    assert.equal(page.items[0]?.status, AttendanceStatus.Present);
    assert.equal(page.items[0]?.subject.code, "SWE-101");
  });

  it("TC-AC-14-004: student history cursor pagination", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026200", "pag@example.edu.vn", "Pag Student");

    for (let i = 0; i < 45; i++) {
      const closedAt = new Date(Date.UTC(2026, 5, 1 + i, 8, 0, 0));
      const sessionId = await seedClosedSession(instructor.userId, closedAt);
      await seedAttendanceRecord(sessionId, student.userId, AttendanceStatus.Present);
    }

    const page1 = await attendanceService.getStudentHistory(student.userId, {
      limit: 20,
    });
    assert.equal(page1.items.length, 20);
    assert.equal(page1.totalCount, 45);
    assert.ok(page1.nextCursor);

    const page2 = await attendanceService.getStudentHistory(student.userId, {
      limit: 20,
      cursor: page1.nextCursor!,
    });
    assert.equal(page2.items.length, 20);
    assert.ok(page2.nextCursor);

    const page3 = await attendanceService.getStudentHistory(student.userId, {
      limit: 20,
      cursor: page2.nextCursor!,
    });
    assert.equal(page3.items.length, 5);
    assert.equal(page3.nextCursor, null);
  });

  it("TC-AC-11-005: PATCH /attendance/:recordId returns 200 with updated record", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026301", "patch@example.edu.vn", "Patch Student");
    const closedAt = new Date("2026-06-28T12:00:00.000Z");
    setClock(new Date(closedAt.getTime() + 60 * 60 * 1000));
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    const recordId = await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Absent,
    );

    const response = await app.inject({
      method: "PATCH",
      url: `/api/v1/attendance/${recordId}`,
      headers: { cookie: instructor.cookie },
      payload: {
        status: AttendanceStatus.Present,
        note: "Ghi chú điểm danh",
      },
    });

    assert.equal(response.statusCode, 200);
    const body = response.json() as { id: string; status: string; studentId: string };
    assert.equal(body.id, recordId);
    assert.equal(body.status, AttendanceStatus.Present);
    assert.equal(body.studentId, student.userId);
  });

  it("TC-AC-11-006: instructor edit at 25 h returns 403 EditWindowExpired", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026302", "late@example.edu.vn", "Late Student");
    const closedAt = new Date("2026-06-27T08:00:00.000Z");
    setClock(new Date(closedAt.getTime() + 25 * 60 * 60 * 1000));
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    const recordId = await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Absent,
    );

    const response = await app.inject({
      method: "PATCH",
      url: `/api/v1/attendance/${recordId}`,
      headers: { cookie: instructor.cookie },
      payload: { status: AttendanceStatus.Present, note: "Late override" },
    });

    assert.equal(response.statusCode, 403);
    const body = response.json() as { errorCode: string };
    assert.equal(body.errorCode, ErrorCode.EditWindowExpired);

    const auditCount = await auditRepo.countForRecord(recordId);
    assert.equal(auditCount, 0);
  });

  it("TC-AC-11-009: student denied PATCH /attendance", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026303", "self@example.edu.vn", "Self Student");
    const closedAt = new Date("2026-06-28T14:00:00.000Z");
    setClock(new Date(closedAt.getTime() + 60 * 60 * 1000));
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    const recordId = await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Absent,
    );

    const response = await app.inject({
      method: "PATCH",
      url: `/api/v1/attendance/${recordId}`,
      headers: { cookie: student.cookie },
      payload: { status: AttendanceStatus.Present, note: "Self mark" },
    });

    assert.equal(response.statusCode, 403);
  });

  it("TC-AC-11-010: unassigned instructor denied manual edit", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const other = await seedUnassignedInstructor();
    const student = await seedStudent("SV2026304", "cross@example.edu.vn", "Cross Student");
    const closedAt = new Date("2026-06-28T16:00:00.000Z");
    setClock(new Date(closedAt.getTime() + 60 * 60 * 1000));
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    const recordId = await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Absent,
    );

    const response = await app.inject({
      method: "PATCH",
      url: `/api/v1/attendance/${recordId}`,
      headers: { cookie: other.cookie },
      payload: { status: AttendanceStatus.Present, note: "Cross-instructor edit" },
    });

    assert.equal(response.statusCode, 403);
  });

  it("TC-AC-14-003: GET /attendance/me/history returns paginated envelope", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026401", "hist@example.edu.vn", "History Student");
    const closedAt = new Date("2026-06-20T08:00:00.000Z");
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    const recordId = await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Present,
    );
    await db.query(
      `UPDATE attendance_records SET checked_in_at = $2 WHERE id = $1`,
      [recordId, closedAt],
    );

    const response = await app.inject({
      method: "GET",
      url: "/api/v1/attendance/me/history?limit=20",
      headers: { cookie: student.cookie },
    });

    assert.equal(response.statusCode, 200);
    const body = response.json() as {
      items: Array<{ status: string; checkedInAt: string | null; sessionDate: string }>;
      nextCursor: string | null;
      totalCount: number;
    };
    assert.ok(Array.isArray(body.items));
    assert.equal(body.totalCount, 1);
    assert.equal(body.items[0]?.status, AttendanceStatus.Present);
    assert.ok(body.items[0]?.checkedInAt);
  });

  it("TC-AC-14-005: student denied GET /sessions/:id/attendance peer roster", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026402", "peer@example.edu.vn", "Peer Student");
    const closedAt = new Date("2026-06-21T08:00:00.000Z");
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    await seedAttendanceRecord(sessionId, student.userId, AttendanceStatus.Absent);

    const response = await app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}/attendance`,
      headers: { cookie: student.cookie },
    });

    assert.equal(response.statusCode, 403);
    const body = response.json() as { errorCode: string; records?: unknown };
    assert.equal(body.errorCode, ErrorCode.Forbidden);
    assert.equal(body.records, undefined);
  });

  it("TC-AC-14-010: limit=201 returns 400 InvalidPagination", async () => {
    await resetDb(seedReferenceData);
    const student = await seedStudent("SV2026403", "lim@example.edu.vn", "Limit Student");

    const response = await app.inject({
      method: "GET",
      url: "/api/v1/attendance/me/history?limit=201",
      headers: { cookie: student.cookie },
    });

    assert.equal(response.statusCode, 400);
    assert.equal(response.json().errorCode, ErrorCode.InvalidPagination);
  });

  it("TC-AC-14-011: malformed cursor returns 400 InvalidPagination", async () => {
    await resetDb(seedReferenceData);
    const student = await seedStudent("SV2026404", "cur@example.edu.vn", "Cursor Student");

    const response = await app.inject({
      method: "GET",
      url: "/api/v1/attendance/me/history?cursor=not-a-valid-cursor",
      headers: { cookie: student.cookie },
    });

    assert.equal(response.statusCode, 400);
    assert.equal(response.json().errorCode, ErrorCode.InvalidPagination);
  });

  it("TC-AC-11-002: Flow C close then manual edit within 24 h", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026501", "flowc@example.edu.vn", "Flow C Student");
    await db.query(
      `INSERT INTO enrollments (student_id, class_id, subject_id) VALUES ($1, $2, $3)`,
      [student.userId, CLASS_HESD_01, SUBJECT_SWE_101],
    );

    const scheduledStart = new Date("2026-06-28T08:00:00.000Z");
    setClock(scheduledStart);
    const createRes = await app.inject({
      method: "POST",
      url: "/api/v1/sessions",
      headers: { cookie: instructor.cookie },
      payload: {
        classId: CLASS_HESD_01,
        subjectId: SUBJECT_SWE_101,
        title: "Flow C Session",
        roomName: "Room C",
        roomLatitude: ROOM_LAT,
        roomLongitude: ROOM_LNG,
        scheduledStart: scheduledStart.toISOString(),
      },
    });
    assert.equal(createRes.statusCode, 201);
    const sessionId = createRes.json().id as string;

    const openRes = await app.inject({
      method: "POST",
      url: `/api/v1/sessions/${sessionId}/open`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(openRes.statusCode, 200);

    const closeRes = await app.inject({
      method: "POST",
      url: `/api/v1/sessions/${sessionId}/close`,
      headers: { cookie: instructor.cookie },
    });
    assert.equal(closeRes.statusCode, 200);

    const rosterRes = await app.inject({
      method: "GET",
      url: `/api/v1/sessions/${sessionId}/attendance`,
      headers: { cookie: instructor.cookie },
    });
    const roster = rosterRes.json() as {
      records: Array<{ id: string; status: string }>;
    };
    const absentRecord = roster.records.find((r) => r.status === AttendanceStatus.Absent);
    assert.ok(absentRecord);

    advanceClock(60 * 60 * 1000);
    const patchRes = await app.inject({
      method: "PATCH",
      url: `/api/v1/attendance/${absentRecord.id}`,
      headers: { cookie: instructor.cookie },
      payload: {
        status: AttendanceStatus.Present,
        note: "Điểm danh thủ công sau khi đóng buổi",
      },
    });
    assert.equal(patchRes.statusCode, 200);

    const audit = await auditRepo.findLatestForRecord(absentRecord.id);
    assert.equal(audit?.previousStatus, AttendanceStatus.Absent);
    assert.equal(audit?.newStatus, AttendanceStatus.Present);
  });

  async function refreshCookie(userId: string): Promise<string> {
    const session = await store.createSession(userId);
    return `${SESSION_COOKIE_NAME}=${session.id}`;
  }

  it("TC-AC-10-003 AC-10b: instructor overrides Rejected to Present after spoof flag (NFR-15)", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026701", "spoof@example.edu.vn", "Spoof Student");
    const closedAt = new Date("2026-06-28T10:00:00.000Z");
    setClock(new Date(closedAt.getTime() + 2 * 60 * 60 * 1000));
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    const recordId = await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Rejected,
    );

    await attendanceService.manualEdit(
      recordId,
      {
        status: AttendanceStatus.Present,
        note: "Xác minh trực tiếp sau cảnh báo GPS",
      },
      instructor.userId,
      UserRole.Instructor,
    );

    const audit = await auditRepo.findLatestForRecord(recordId);
    assert.equal(audit?.previousStatus, AttendanceStatus.Rejected);
    assert.equal(audit?.newStatus, AttendanceStatus.Present);
    assert.equal(audit?.note, "Xác minh trực tiếp sau cảnh báo GPS");
  });

  it("TC-NFR-15-017 AC-10c: attendance audit logs reject UPDATE and DELETE (append-only)", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026702", "audit@example.edu.vn", "Audit Student");
    const closedAt = new Date("2026-06-28T11:00:00.000Z");
    setClock(new Date(closedAt.getTime() + 60 * 60 * 1000));
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    const recordId = await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Absent,
    );

    await attendanceService.manualEdit(
      recordId,
      { status: AttendanceStatus.Present, note: "Audit seed" },
      instructor.userId,
      UserRole.Instructor,
    );

    const auditRow = await db.query<{ id: string; new_status: string }>(
      `SELECT id, new_status FROM attendance_audit_logs WHERE attendance_record_id = $1`,
      [recordId],
    );
    const auditId = auditRow.rows[0]?.id;
    assert.ok(auditId);

    await assert.rejects(
      () =>
        db.query(
          `UPDATE attendance_audit_logs SET new_status = $2 WHERE id = $1`,
          [auditId, AttendanceStatus.Absent],
        ),
      /append-only/,
    );

    await assert.rejects(
      () => db.query(`DELETE FROM attendance_audit_logs WHERE id = $1`, [auditId]),
      /append-only/,
    );

    const unchanged = await db.query<{ new_status: string }>(
      `SELECT new_status FROM attendance_audit_logs WHERE id = $1`,
      [auditId],
    );
    assert.equal(unchanged.rows[0]?.new_status, AttendanceStatus.Present);
  });

  it("TC-AC-11-013: edit boundary at exactly 24 h", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student1 = await seedStudent("SV2026601", "b1@example.edu.vn", "Boundary One");
    const student2 = await seedStudent("SV2026602", "b2@example.edu.vn", "Boundary Two");
    const closedAt = new Date("2026-06-28T08:00:00.000Z");
    const sessionId = await seedClosedSession(instructor.userId, closedAt);
    const recordId1 = await seedAttendanceRecord(
      sessionId,
      student1.userId,
      AttendanceStatus.Absent,
    );
    const recordId2 = await seedAttendanceRecord(
      sessionId,
      student2.userId,
      AttendanceStatus.Absent,
    );

    setClock(new Date(closedAt.getTime() + INSTRUCTOR_EDIT_WINDOW_MS - 1000));
    const cookieWithinWindow = await refreshCookie(instructor.userId);
    const okRes = await app.inject({
      method: "PATCH",
      url: `/api/v1/attendance/${recordId1}`,
      headers: { cookie: cookieWithinWindow },
      payload: { status: AttendanceStatus.Present },
    });
    assert.equal(okRes.statusCode, 200);

    setClock(new Date(closedAt.getTime() + INSTRUCTOR_EDIT_WINDOW_MS + 1000));
    const cookiePastWindow = await refreshCookie(instructor.userId);
    const failRes = await app.inject({
      method: "PATCH",
      url: `/api/v1/attendance/${recordId2}`,
      headers: { cookie: cookiePastWindow },
      payload: { status: AttendanceStatus.Present },
    });
    assert.equal(failRes.statusCode, 403);
  });
});
