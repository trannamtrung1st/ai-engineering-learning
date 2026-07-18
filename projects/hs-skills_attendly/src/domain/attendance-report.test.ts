import { eq } from "drizzle-orm";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createDatabase } from "../db/client";
import { auditLogs } from "../db/schema";
import { DEMO, seedAttendanceHistory, seedDatabase } from "../db/seed";
import {
  AttendanceReportError,
  csvEscape,
  exportSectionReportCsv,
  getSectionReport,
  getStudentAttendanceHistory,
} from "./attendance-report";

describe("student attendance history", () => {
  let database: ReturnType<typeof createDatabase>;
  // After seed time, so the live session (seeded at real "now") counts as started.
  const now = new Date(Date.now() + 60_000);

  beforeEach(() => {
    database = createDatabase(":memory:");
    seedDatabase(database.db, database.sqlite);
    seedAttendanceHistory(database.db, now);
  });

  afterEach(() => database.sqlite.close());

  it("lists every past session with status or no record, plus totals", () => {
    const [linhHistory] = getStudentAttendanceHistory(database.db, {
      studentId: DEMO.enrolledStudentIds[0],
      now,
    });

    expect(linhHistory).toMatchObject({
      classSectionId: DEMO.classSectionId,
      sectionName: "AI Engineering 101",
    });
    // Two seeded past sessions plus the current unresolved one.
    expect(linhHistory.sessions).toHaveLength(3);
    const byId = new Map(
      linhHistory.sessions.map((session) => [
        session.classSessionId,
        session.status,
      ]),
    );
    expect(byId.get(DEMO.pastSessionIds[0])).toBe("present");
    expect(byId.get(DEMO.pastSessionIds[1])).toBe("late");
    expect(byId.get(DEMO.classSessionId)).toBeNull();
    expect(linhHistory.totals).toEqual({
      present: 1,
      late: 1,
      absent: 0,
      excused: 0,
      manual_present: 0,
    });
  });

  it("keeps each student's history separate", () => {
    const [minhHistory] = getStudentAttendanceHistory(database.db, {
      studentId: DEMO.enrolledStudentIds[1],
      now,
    });

    expect(minhHistory.totals).toEqual({
      present: 0,
      late: 0,
      absent: 1,
      excused: 1,
      manual_present: 0,
    });
    expect(
      minhHistory.sessions.every((session) => session.status !== "present"),
    ).toBe(true);
  });

  it("returns nothing for a student with no enrollments", () => {
    expect(
      getStudentAttendanceHistory(database.db, {
        studentId: DEMO.nonEnrolledStudentId,
        now,
      }),
    ).toEqual([]);
  });

  it("excludes sessions that have not started yet", () => {
    const beforeEverything = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    const [history] = getStudentAttendanceHistory(database.db, {
      studentId: DEMO.enrolledStudentIds[0],
      now: beforeEverything,
    });

    expect(history.sessions).toHaveLength(0);
  });
});

describe("section report", () => {
  let database: ReturnType<typeof createDatabase>;

  beforeEach(() => {
    database = createDatabase(":memory:");
    seedDatabase(database.db, database.sqlite);
    seedAttendanceHistory(database.db);
  });

  afterEach(() => database.sqlite.close());

  it("returns one row per enrolled student with counts and rate", () => {
    const report = getSectionReport(database.db, {
      classSectionId: DEMO.classSectionId,
      lecturerId: DEMO.lecturerId,
    });

    expect(report).toMatchObject({
      classSectionId: DEMO.classSectionId,
      sectionName: "AI Engineering 101",
    });
    expect(report.rows).toHaveLength(DEMO.enrolledStudentIds.length);

    const linh = report.rows.find(
      (row) => row.studentId === DEMO.enrolledStudentIds[0],
    );
    expect(linh).toMatchObject({
      counts: { present: 1, late: 1, absent: 0, excused: 0, manual_present: 0 },
      attendanceRate: 1,
    });

    const minh = report.rows.find(
      (row) => row.studentId === DEMO.enrolledStudentIds[1],
    );
    expect(minh).toMatchObject({
      counts: { present: 0, late: 0, absent: 1, excused: 1, manual_present: 0 },
      attendanceRate: 0.5,
    });
  });

  it("excludes non-enrolled students and unresolved sessions", () => {
    const report = getSectionReport(database.db, {
      classSectionId: DEMO.classSectionId,
      lecturerId: DEMO.lecturerId,
    });

    expect(
      report.rows.some((row) => row.studentId === DEMO.nonEnrolledStudentId),
    ).toBe(false);
    // The live session has no records, so each student's resolved count
    // stays at the two seeded past sessions.
    for (const row of report.rows) {
      const resolved = Object.values(row.counts).reduce((a, b) => a + b, 0);
      expect(resolved).toBe(2);
    }
  });

  it("returns a null rate when nothing is resolved", () => {
    const clean = createDatabase(":memory:");
    seedDatabase(clean.db, clean.sqlite);

    const report = getSectionReport(clean.db, {
      classSectionId: DEMO.classSectionId,
      lecturerId: DEMO.lecturerId,
    });
    expect(report.rows.every((row) => row.attendanceRate === null)).toBe(true);
    clean.sqlite.close();
  });

  it("rejects a non-owner lecturer and a missing section", () => {
    expect(() =>
      getSectionReport(database.db, {
        classSectionId: DEMO.classSectionId,
        lecturerId: DEMO.enrolledStudentIds[0],
      }),
    ).toThrowError(new AttendanceReportError("not_owner"));
    expect(() =>
      getSectionReport(database.db, {
        classSectionId: "missing-section",
        lecturerId: DEMO.lecturerId,
      }),
    ).toThrowError(new AttendanceReportError("section_not_found"));
  });
});

describe("section report CSV export", () => {
  let database: ReturnType<typeof createDatabase>;
  const now = new Date("2026-07-18T09:00:00Z");

  beforeEach(() => {
    database = createDatabase(":memory:");
    seedDatabase(database.db, database.sqlite);
    seedAttendanceHistory(database.db);
  });

  afterEach(() => database.sqlite.close());

  it("renders the same rows as the report and writes an audit entry", () => {
    const report = getSectionReport(database.db, {
      classSectionId: DEMO.classSectionId,
      lecturerId: DEMO.lecturerId,
    });
    const { csv, auditLogId } = exportSectionReportCsv(database.db, {
      classSectionId: DEMO.classSectionId,
      lecturerId: DEMO.lecturerId,
      now,
    });

    const lines = csv.trim().split("\n");
    expect(lines[0]).toBe(
      "student_id,student_name,present,late,absent,excused,manual_present,attendance_rate",
    );
    expect(lines).toHaveLength(report.rows.length + 1);
    const linh = report.rows.find(
      (row) => row.studentId === DEMO.enrolledStudentIds[0],
    )!;
    expect(lines).toContain(
      `${linh.studentId},${linh.studentName},1,1,0,0,0,1.00`,
    );
    const minh = report.rows.find(
      (row) => row.studentId === DEMO.enrolledStudentIds[1],
    )!;
    expect(lines).toContain(
      `${minh.studentId},${minh.studentName},0,0,1,1,0,0.50`,
    );

    const audit = database.db
      .select()
      .from(auditLogs)
      .where(eq(auditLogs.id, auditLogId))
      .get();
    expect(audit).toMatchObject({
      actorId: DEMO.lecturerId,
      attendanceRecordId: null,
      action: "attendance.report_exported",
      createdAt: now,
    });
    expect(JSON.parse(audit!.newValue)).toMatchObject({
      classSectionId: DEMO.classSectionId,
      rowCount: report.rows.length,
    });
  });

  it("rejects a non-owner without writing an audit entry", () => {
    expect(() =>
      exportSectionReportCsv(database.db, {
        classSectionId: DEMO.classSectionId,
        lecturerId: DEMO.enrolledStudentIds[0],
      }),
    ).toThrowError(new AttendanceReportError("not_owner"));
    expect(database.db.select().from(auditLogs).all()).toHaveLength(0);
  });

  it("renders an empty attendance_rate cell when nothing is resolved", () => {
    const clean = createDatabase(":memory:");
    seedDatabase(clean.db, clean.sqlite);

    const { csv } = exportSectionReportCsv(clean.db, {
      classSectionId: DEMO.classSectionId,
      lecturerId: DEMO.lecturerId,
      now,
    });
    const dataRows = csv.trim().split("\n").slice(1);
    expect(dataRows.length).toBeGreaterThan(0);
    for (const row of dataRows) {
      expect(row.endsWith(",")).toBe(true);
    }
    clean.sqlite.close();
  });
});

describe("csvEscape", () => {
  it("quotes values containing commas, quotes, or newlines", () => {
    expect(csvEscape("plain")).toBe("plain");
    expect(csvEscape("a,b")).toBe('"a,b"');
    expect(csvEscape('she said "hi"')).toBe('"she said ""hi"""');
    expect(csvEscape("line1\nline2")).toBe('"line1\nline2"');
  });

  it("neutralizes leading formula characters", () => {
    expect(csvEscape("=SUM(A1)")).toBe("'=SUM(A1)");
    expect(csvEscape("+1")).toBe("'+1");
    expect(csvEscape("-1")).toBe("'-1");
    expect(csvEscape("@cmd")).toBe("'@cmd");
    // A guarded value that also needs quoting gets both treatments.
    expect(csvEscape("=1,2")).toBe(`"'=1,2"`);
  });
});
