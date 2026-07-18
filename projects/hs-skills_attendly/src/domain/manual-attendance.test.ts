import { eq } from "drizzle-orm";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createDatabase } from "../db/client";
import { DEMO, seedDatabase } from "../db/seed";
import { attendanceRecords, auditLogs } from "../db/schema";
import { checkIn } from "./check-in";
import {
  getSessionRoster,
  ManualAttendanceError,
  markManualPresent,
} from "./manual-attendance";
import { clearActiveQrCache, openAttendance } from "./qr-session";

describe("manual attendance", () => {
  let database: ReturnType<typeof createDatabase>;
  const now = new Date("2026-07-18T08:10:00Z");

  beforeEach(() => {
    database = createDatabase(":memory:");
    seedDatabase(database.db, database.sqlite);
    clearActiveQrCache();
  });

  afterEach(() => database.sqlite.close());

  it("creates Manual Present and a complete audit entry", () => {
    const result = markManualPresent(database.db, {
      lecturerId: DEMO.lecturerId,
      classSessionId: DEMO.classSessionId,
      studentId: DEMO.enrolledStudentIds[0],
      reason: "Student phone battery was empty",
      now,
    });
    const attendance = database.db
      .select()
      .from(attendanceRecords)
      .where(eq(attendanceRecords.id, result.attendanceRecordId))
      .get();
    const audit = database.db
      .select()
      .from(auditLogs)
      .where(eq(auditLogs.id, result.auditLogId))
      .get();

    expect(attendance).toMatchObject({
      status: "manual_present",
      method: "manual",
    });
    expect(audit).toMatchObject({
      actorId: DEMO.lecturerId,
      oldValue: null,
      reason: "Student phone battery was empty",
      createdAt: now,
    });
    expect(JSON.parse(audit!.newValue)).toMatchObject({
      status: "manual_present",
      method: "manual",
    });
  });

  it("updates an existing QR record and audits before and after", () => {
    const openedAt = new Date(now.getTime() - 5_000);
    const qr = openAttendance(
      database.db,
      DEMO.classSessionId,
      DEMO.lecturerId,
      openedAt,
    );
    checkIn(database.db, {
      studentId: DEMO.enrolledStudentIds[0],
      classSessionId: DEMO.classSessionId,
      token: qr.token,
      now: openedAt,
    });

    markManualPresent(database.db, {
      lecturerId: DEMO.lecturerId,
      classSessionId: DEMO.classSessionId,
      studentId: DEMO.enrolledStudentIds[0],
      reason: "Lecturer verified attendance",
      now,
    });
    const audit = database.db.select().from(auditLogs).get();

    expect(JSON.parse(audit!.oldValue!)).toMatchObject({
      status: "present",
      method: "qr",
    });
    expect(JSON.parse(audit!.newValue)).toMatchObject({
      status: "manual_present",
      method: "manual",
    });
    expect(database.db.select().from(attendanceRecords).all()).toHaveLength(1);
  });

  it("requires a reason and the owning lecturer", () => {
    expect(() =>
      markManualPresent(database.db, {
        lecturerId: DEMO.lecturerId,
        classSessionId: DEMO.classSessionId,
        studentId: DEMO.enrolledStudentIds[0],
        reason: " ",
      }),
    ).toThrowError(new ManualAttendanceError("invalid_reason"));
    expect(() =>
      markManualPresent(database.db, {
        lecturerId: DEMO.enrolledStudentIds[0],
        classSessionId: DEMO.classSessionId,
        studentId: DEMO.enrolledStudentIds[1],
        reason: "Not allowed",
      }),
    ).toThrowError(new ManualAttendanceError("not_owner"));
  });

  it("returns the enrolled roster with current status", () => {
    markManualPresent(database.db, {
      lecturerId: DEMO.lecturerId,
      classSessionId: DEMO.classSessionId,
      studentId: DEMO.enrolledStudentIds[0],
      reason: "Verified in person",
      now,
    });
    const roster = getSessionRoster(database.db, DEMO.classSessionId);

    expect(roster).toHaveLength(DEMO.enrolledStudentIds.length);
    expect(roster.map((entry) => entry.studentId)).toEqual(
      expect.arrayContaining([...DEMO.enrolledStudentIds]),
    );
    expect(
      roster.find((entry) => entry.studentId === DEMO.enrolledStudentIds[0])
        ?.status,
    ).toBe("manual_present");
    expect(
      roster.find((entry) => entry.studentId === DEMO.enrolledStudentIds[1])
        ?.status,
    ).toBeNull();
    expect(
      roster.some((entry) => entry.studentId === DEMO.nonEnrolledStudentId),
    ).toBe(false);
  });
});
