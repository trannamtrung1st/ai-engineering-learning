import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import {
  AttendanceStatus,
  ErrorCode,
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
import { truncateRosterTables } from "../roster-enrollment/roster-service.js";
import { truncateSessionTables } from "../session-management/session-service.js";
import { ApiError } from "../../errors/api-error.js";
import { withIntegrationTestDbReset } from "../../infra/integration-test-lock.js";
import { CSV_HEADERS } from "./csv-formatter.js";
import { ExportService } from "./export-service.js";
import {
  ExportAuditRepository,
  ExportSecurityAuditRepository,
  truncateReportingTables,
} from "./repositories.js";
import { ReportService } from "./report-service.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

const CLASS_HESD_01 = "10000000-0000-4000-8000-000000000101";
const CLASS_HESD_02 = "10000000-0000-4000-8000-000000000102";
const SUBJECT_SWE_101 = "20000000-0000-4000-8000-000000000201";
const SUBJECT_SWE_102 = "20000000-0000-4000-8000-000000000202";

const ROOM_LAT = 10.762622;
const ROOM_LNG = 106.660172;

/**
 * Traceability: AC-12 AC-13 FR-12 FR-13 BR-08 BR-09 NFR-07 NFR-11 NFR-15
 * Integration: TC-AC-12-002 TC-AC-12-009 TC-AC-13-003 TC-AC-13-004
 * TC-FR-12-002 TC-FR-12-009 TC-FR-13-003 TC-FR-13-004 TC-BR-08-002 TC-BR-08-009
 * TC-BR-09-003 TC-BR-09-004 TC-NFR-07-002 TC-NFR-07-014 TC-NFR-11-002 TC-NFR-15-002
 */
describe("reporting-export integration (AC-12, AC-13, FR-12, FR-13, BR-08, BR-09, NFR-07, NFR-11, NFR-15)", () => {
  let db: DbPool;
  let app: Awaited<ReturnType<typeof buildApp>>;
  let store: SessionStore;
  let reportService: ReportService;
  let exportService: ExportService;
  let exportAudit: ExportAuditRepository;
  let securityAudit: ExportSecurityAuditRepository;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
    app = await buildApp({ db, logger: false });
    store = new SessionStore(db);
    reportService = new ReportService(db);
    exportService = new ExportService(db);
    exportAudit = new ExportAuditRepository(db);
    securityAudit = new ExportSecurityAuditRepository(db);
  });

  after(async () => {
    resetClock();
    await app.close();
    await closePool();
  });

  async function resetDb(afterTruncate?: () => Promise<void>): Promise<void> {
    await withIntegrationTestDbReset(db, async () => {
      await truncateSessionTables(db);
      await truncateReportingTables(db);
      await truncateRosterTables(db);
      await truncateAuthTables(db);
      resetClock();
      if (afterTruncate) await afterTruncate();
    });
  }

  async function seedReferenceData(): Promise<void> {
    await db.query(
      `INSERT INTO classes (id, code, name) VALUES
       ($1, 'HESD-01', 'HESD Cohort A'),
       ($2, 'HESD-02', 'HESD Cohort B')
       ON CONFLICT (id) DO NOTHING`,
      [CLASS_HESD_01, CLASS_HESD_02],
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
    assignHesd01 = true,
  ): Promise<{ userId: string; cookie: string }> {
    const userId = await createTestUser(db, {
      institutionalId: "GV2026001",
      displayName: "Instructor One",
      email,
      role: UserRole.Instructor,
    });
    if (assignHesd01) {
      await db.query(
        `INSERT INTO class_assignments (instructor_id, class_id, subject_id)
         VALUES ($1, $2, $3)`,
        [userId, CLASS_HESD_01, SUBJECT_SWE_101],
      );
    }
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

  async function seedClosedSession(
    instructorId: string,
    scheduledStart: Date,
    classId = CLASS_HESD_01,
    subjectId = SUBJECT_SWE_101,
  ): Promise<string> {
    const sessionId = crypto.randomUUID();
    await db.query(
      `INSERT INTO sessions
         (id, instructor_id, class_id, subject_id, title, room_name,
          room_latitude, room_longitude, gps_radius_meters, scheduled_start,
          status, opened_at, closed_at)
       VALUES ($1, $2, $3, $4, 'Workshop', 'Room A', $5, $6, 100, $7, $8, $7, $7)`,
      [
        sessionId,
        instructorId,
        classId,
        subjectId,
        ROOM_LAT,
        ROOM_LNG,
        scheduledStart,
        SessionStatus.Closed,
      ],
    );
    return sessionId;
  }

  async function seedEnrollment(
    studentId: string,
    classId: string,
    subjectId: string,
  ): Promise<void> {
    await db.query(
      `INSERT INTO enrollments (student_id, class_id, subject_id) VALUES ($1, $2, $3)`,
      [studentId, classId, subjectId],
    );
  }

  async function seedAttendanceRecord(
    sessionId: string,
    studentId: string,
    status: AttendanceStatus,
    checkedInAt?: Date,
  ): Promise<void> {
    await db.query(
      `INSERT INTO attendance_records (id, session_id, student_id, status, checked_in_at)
       VALUES ($1, $2, $3, $4, $5)`,
      [crypto.randomUUID(), sessionId, studentId, status, checkedInAt ?? null],
    );
  }

  it("TC-AC-12-002: getClassSubjectSummary scoped to ClassAssignment (BR-08)", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026001", "s1@example.edu.vn", "Student One");
    await seedEnrollment(student.userId, CLASS_HESD_01, SUBJECT_SWE_101);

    const sessionDate = new Date("2026-06-15T08:00:00.000Z");
    const sessionId = await seedClosedSession(instructor.userId, sessionDate);
    await seedAttendanceRecord(sessionId, student.userId, AttendanceStatus.Present, sessionDate);

    const assignedSummary = await reportService.getClassSubjectSummary(
      { classCode: "HESD-01", subjectCode: "SWE-101", from: "2026-06-01", to: "2026-06-30" },
      instructor.userId,
      UserRole.Instructor,
    );
    assert.equal(assignedSummary.classCode, "HESD-01");
    assert.equal(assignedSummary.sessionsHeld, 1);
    assert.equal(assignedSummary.students.length, 1);
    assert.equal(assignedSummary.students[0]?.presentCount, 1);

    await assert.rejects(
      () =>
        reportService.getClassSubjectSummary(
          { classCode: "HESD-02", subjectCode: "SWE-102", from: "2026-06-01", to: "2026-06-30" },
          instructor.userId,
          UserRole.Instructor,
        ),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.errorCode, ErrorCode.ReportAccessDenied);
        return true;
      },
    );
  });

  it("TC-AC-12-009: getSessionRoster enforces assignment scope (BR-08)", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026002", "s2@example.edu.vn", "Student Two");
    await seedEnrollment(student.userId, CLASS_HESD_01, SUBJECT_SWE_101);

    const assignedSessionId = await seedClosedSession(
      instructor.userId,
      new Date("2026-06-10T08:00:00.000Z"),
    );
    await seedAttendanceRecord(
      assignedSessionId,
      student.userId,
      AttendanceStatus.Absent,
    );

    const unassignedSessionId = await seedClosedSession(
      instructor.userId,
      new Date("2026-06-11T08:00:00.000Z"),
      CLASS_HESD_02,
      SUBJECT_SWE_102,
    );
    await seedAttendanceRecord(
      unassignedSessionId,
      student.userId,
      AttendanceStatus.Present,
    );

    const assignedReport = await reportService.getSessionRoster(
      assignedSessionId,
      instructor.userId,
      UserRole.Instructor,
    );
    assert.equal(assignedReport.records.length, 1);
    assert.equal(assignedReport.summary.absent, 1);

    await assert.rejects(
      () =>
        reportService.getSessionRoster(
          unassignedSessionId,
          instructor.userId,
          UserRole.Instructor,
        ),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.errorCode, ErrorCode.ReportAccessDenied);
        return true;
      },
    );
  });

  it("TC-FR-12-002: summary aggregates present/absent/excused and attendanceRate", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const studentA = await seedStudent("SV2026010", "sa@example.edu.vn", "Student A");
    const studentB = await seedStudent("SV2026011", "sb@example.edu.vn", "Student B");
    await seedEnrollment(studentA.userId, CLASS_HESD_01, SUBJECT_SWE_101);
    await seedEnrollment(studentB.userId, CLASS_HESD_01, SUBJECT_SWE_101);

    const session1 = await seedClosedSession(
      instructor.userId,
      new Date("2026-06-05T08:00:00.000Z"),
    );
    const session2 = await seedClosedSession(
      instructor.userId,
      new Date("2026-06-12T08:00:00.000Z"),
    );
    await seedAttendanceRecord(session1, studentA.userId, AttendanceStatus.Present);
    await seedAttendanceRecord(session1, studentB.userId, AttendanceStatus.Absent);
    await seedAttendanceRecord(session2, studentA.userId, AttendanceStatus.Present);
    await seedAttendanceRecord(session2, studentB.userId, AttendanceStatus.Excused);

    const summary = await reportService.getClassSubjectSummary(
      { classCode: "HESD-01", subjectCode: "SWE-101", from: "2026-06-01", to: "2026-06-30" },
      instructor.userId,
      UserRole.Instructor,
    );

    assert.equal(summary.sessionsHeld, 2);
    const rowA = summary.students.find((s) => s.institutionalId === "SV2026010");
    const rowB = summary.students.find((s) => s.institutionalId === "SV2026011");
    assert.equal(rowA?.presentCount, 2);
    assert.equal(rowA?.attendanceRate, 1);
    assert.equal(rowB?.absentCount, 1);
    assert.equal(rowB?.excusedCount, 1);
    assert.equal(rowB?.attendanceRate, 0);
  });

  it("TC-AC-13-003: exportCsv produces spec columns from PostgreSQL (FR-13)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026020", "s20@example.edu.vn", "Nguyễn Văn A");
    await seedEnrollment(student.userId, CLASS_HESD_01, SUBJECT_SWE_101);

    const checkedInAt = new Date("2026-06-20T08:05:12.000Z");
    const sessionId = await seedClosedSession(
      instructor.userId,
      new Date("2026-06-20T08:00:00.000Z"),
    );
    await seedAttendanceRecord(
      sessionId,
      student.userId,
      AttendanceStatus.Present,
      checkedInAt,
    );

    const result = await exportService.exportCsv(
      { classCode: "HESD-01", subjectCode: "SWE-101", from: "2026-06-01", to: "2026-06-30" },
      admin.userId,
      UserRole.TrainingOfficeAdmin,
    );

    const lines = result.csv.trimEnd().split("\n");
    assert.equal(lines[0], CSV_HEADERS.join(","));
    assert.equal(result.rowCount, 1);
    assert.match(lines[1]!, /SV2026020/);
    assert.match(lines[1]!, /Nguyễn Văn A/);
    assert.match(lines[1]!, /Present/);
    assert.match(lines[1]!, /2026-06-20T08:05:12.000Z/);
  });

  it("TC-AC-13-004: successful export writes ExportAuditLog (NFR-15)", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026021", "s21@example.edu.vn", "Student Export");
    await seedEnrollment(student.userId, CLASS_HESD_01, SUBJECT_SWE_101);
    const sessionId = await seedClosedSession(
      instructor.userId,
      new Date("2026-06-18T08:00:00.000Z"),
    );
    await seedAttendanceRecord(sessionId, student.userId, AttendanceStatus.Absent);

    const beforeCount = await exportAudit.countByAdmin(admin.userId);
    const result = await exportService.exportCsv(
      { classCode: "HESD-01", subjectCode: "SWE-101", from: "2026-06-01", to: "2026-06-30" },
      admin.userId,
      UserRole.TrainingOfficeAdmin,
    );

    assert.equal(result.rowCount, 1);
    const afterCount = await exportAudit.countByAdmin(admin.userId);
    assert.equal(afterCount, beforeCount + 1);

    const audit = await exportAudit.findLatestByAdmin(admin.userId);
    assert.ok(audit);
    assert.equal(audit.adminId, admin.userId);
    assert.equal(audit.rowCount, 1);
    assert.equal(audit.filterSummary.classCode, "HESD-01");
    assert.equal(audit.filterSummary.subjectCode, "SWE-101");
    assert.equal(audit.filterSummary.from, "2026-06-01");
    assert.equal(audit.filterSummary.to, "2026-06-30");
  });

  it("TC-BR-09-003: exportCsv rejects non-admin and permits admin (BR-09)", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const admin = await seedAdmin();

    await assert.rejects(
      () =>
        exportService.exportCsv(
          { classCode: "HESD-01", subjectCode: "SWE-101", from: "2026-06-01", to: "2026-06-30" },
          instructor.userId,
          UserRole.Instructor,
        ),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.errorCode, ErrorCode.ExportNotAllowed);
        return true;
      },
    );

    const success = await exportService.exportCsv(
      { classCode: "HESD-01", subjectCode: "SWE-101", from: "2026-06-01", to: "2026-06-30" },
      admin.userId,
      UserRole.TrainingOfficeAdmin,
    );
    assert.ok(success.csv.startsWith(CSV_HEADERS.join(",")));
  });

  it("TC-BR-09-004: denied export writes ExportDenied security audit (NFR-11, NFR-15)", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const beforeDenied = await securityAudit.countExportDenied(instructor.userId);

    await assert.rejects(
      () =>
        exportService.exportCsv(
          { classCode: "HESD-01", subjectCode: "SWE-101", from: "2026-06-01", to: "2026-06-30" },
          instructor.userId,
          UserRole.Instructor,
        ),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        return true;
      },
    );

    const afterDenied = await securityAudit.countExportDenied(instructor.userId);
    assert.equal(afterDenied, beforeDenied + 1);
    assert.equal(await exportAudit.countByAdmin(instructor.userId), 0);
  });

  it("TC-AC-12-003: GET /reports/summary HTTP 200 contract", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-01&subjectCode=SWE-101&from=2026-06-01&to=2026-06-30",
      headers: { cookie: instructor.cookie },
    });
    assert.equal(response.statusCode, 200);
    assert.match(response.headers["content-type"] ?? "", /application\/json/);
    const body = response.json<{
      classCode: string;
      subjectCode: string;
      dateFrom: string;
      dateTo: string;
      sessionsHeld: number;
      students: unknown[];
    }>();
    assert.equal(body.classCode, "HESD-01");
    assert.equal(body.subjectCode, "SWE-101");
    assert.equal(body.dateFrom, "2026-06-01");
    assert.equal(body.dateTo, "2026-06-30");
    assert.ok(Array.isArray(body.students));
  });

  it("TC-AC-12-004: unassigned instructor GET /reports/summary returns 403 ReportAccessDenied", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor("unassigned@example.edu.vn", true);
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-02&subjectCode=SWE-102&from=2026-06-01&to=2026-06-30",
      headers: { cookie: instructor.cookie },
    });
    assert.equal(response.statusCode, 403);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.ReportAccessDenied,
    );
  });

  it("TC-AC-12-008: invalid date range returns 422 ValidationFailed", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const response = await app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?classCode=HESD-01&subjectCode=SWE-101&from=2026-06-30&to=2026-06-01",
      headers: { cookie: instructor.cookie },
    });
    assert.equal(response.statusCode, 422);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.ValidationFailed,
    );
  });

  it("TC-AC-13-005: POST /reports/export returns CSV attachment", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/reports/export",
      headers: { cookie: admin.cookie },
      payload: {
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        from: "2026-06-01",
        to: "2026-06-30",
      },
    });
    assert.equal(response.statusCode, 200);
    assert.match(response.headers["content-type"] ?? "", /text\/csv/);
    assert.match(
      response.headers["content-disposition"] ?? "",
      /attachment; filename="attendance-export-/,
    );
    assert.equal(response.body.split("\n")[0], CSV_HEADERS.join(","));
  });

  it("TC-AC-13-006 TC-NFR-15-012: Instructor POST /reports/export returns ExportNotAllowed with ExportDenied audit", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const beforeDenied = await securityAudit.countExportDenied(instructor.userId);

    const response = await app.inject({
      method: "POST",
      url: "/api/v1/reports/export",
      headers: { cookie: instructor.cookie },
      payload: {
        classCode: "HESD-01",
        subjectCode: "SWE-101",
        from: "2026-06-01",
        to: "2026-06-30",
      },
    });
    assert.equal(response.statusCode, 403);
    assert.equal(
      response.json<{ errorCode: string }>().errorCode,
      ErrorCode.ExportNotAllowed,
    );
    assert.equal(
      await securityAudit.countExportDenied(instructor.userId),
      beforeDenied + 1,
    );
    assert.equal(await exportAudit.countByAdmin(instructor.userId), 0);
  });

  it("TC-BR-08-006: admin institution-wide summary without class filter", async () => {
    await resetDb(seedReferenceData);
    const admin = await seedAdmin();
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026030", "s30@example.edu.vn", "Cross Cohort");
    await seedEnrollment(student.userId, CLASS_HESD_01, SUBJECT_SWE_101);
    await seedEnrollment(student.userId, CLASS_HESD_02, SUBJECT_SWE_102);

    const session1 = await seedClosedSession(
      instructor.userId,
      new Date("2026-06-08T08:00:00.000Z"),
      CLASS_HESD_01,
      SUBJECT_SWE_101,
    );
    const session2 = await seedClosedSession(
      instructor.userId,
      new Date("2026-06-09T08:00:00.000Z"),
      CLASS_HESD_02,
      SUBJECT_SWE_102,
    );
    await seedAttendanceRecord(session1, student.userId, AttendanceStatus.Present);
    await seedAttendanceRecord(session2, student.userId, AttendanceStatus.Absent);

    const response = await app.inject({
      method: "GET",
      url: "/api/v1/reports/summary?from=2026-06-01&to=2026-06-30",
      headers: { cookie: admin.cookie },
    });
    assert.equal(response.statusCode, 200);
    const body = response.json<{ sessionsHeld: number; students: unknown[] }>();
    assert.equal(body.sessionsHeld, 2);
    assert.ok(body.students.length >= 1);
  });

  it("TC-NFR-07-002: report available immediately after session close", async () => {
    await resetDb(seedReferenceData);
    const instructor = await seedInstructor();
    const student = await seedStudent("SV2026040", "s40@example.edu.vn", "Latency Student");
    await seedEnrollment(student.userId, CLASS_HESD_01, SUBJECT_SWE_101);

    const sessionId = await seedClosedSession(
      instructor.userId,
      new Date("2026-06-22T08:00:00.000Z"),
    );
    await seedAttendanceRecord(sessionId, student.userId, AttendanceStatus.Present);

    const report = await reportService.getSessionRoster(
      sessionId,
      instructor.userId,
      UserRole.Instructor,
    );
    assert.equal(report.summary.present, 1);
    assert.equal(report.summary.pending, 0);
  });
});
