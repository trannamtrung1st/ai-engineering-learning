import { eq } from "drizzle-orm";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createDatabase } from "../db/client";
import { DEMO, seedDatabase } from "../db/seed";
import { attendanceRecords, auditLogs } from "../db/schema";
import { checkIn } from "./check-in";
import {
  getSessionRoster,
  MANUAL_ATTENDANCE_STATUSES,
  ManualAttendanceError,
  setManualAttendance,
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

  it.each(MANUAL_ATTENDANCE_STATUSES)(
    "creates %s and a complete audit entry",
    (status) => {
      const result = setManualAttendance(database.db, {
        lecturerId: DEMO.lecturerId,
        classSessionId: DEMO.classSessionId,
        studentId: DEMO.enrolledStudentIds[0],
        status,
        reason: "Lecturer verified attendance",
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

      expect(result.status).toBe(status);
      expect(attendance).toMatchObject({ status, method: "manual" });
      expect(audit).toMatchObject({
        actorId: DEMO.lecturerId,
        action: "attendance.manual_set",
        oldValue: null,
        reason: "Lecturer verified attendance",
        createdAt: now,
      });
      expect(JSON.parse(audit!.newValue)).toMatchObject({
        status,
        method: "manual",
      });
    },
  );

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

    setManualAttendance(database.db, {
      lecturerId: DEMO.lecturerId,
      classSessionId: DEMO.classSessionId,
      studentId: DEMO.enrolledStudentIds[0],
      status: "excused",
      reason: "Lecturer verified attendance",
      now,
    });
    const audit = database.db.select().from(auditLogs).get();

    expect(JSON.parse(audit!.oldValue!)).toMatchObject({
      status: "present",
      method: "qr",
    });
    expect(JSON.parse(audit!.newValue)).toMatchObject({
      status: "excused",
      method: "manual",
    });
    expect(database.db.select().from(attendanceRecords).all()).toHaveLength(1);
  });

  it("requires a reason and the owning lecturer", () => {
    expect(() =>
      setManualAttendance(database.db, {
        lecturerId: DEMO.lecturerId,
        classSessionId: DEMO.classSessionId,
        studentId: DEMO.enrolledStudentIds[0],
        status: "manual_present",
        reason: " ",
      }),
    ).toThrowError(new ManualAttendanceError("invalid_reason"));
    expect(() =>
      setManualAttendance(database.db, {
        lecturerId: DEMO.enrolledStudentIds[0],
        classSessionId: DEMO.classSessionId,
        studentId: DEMO.enrolledStudentIds[1],
        status: "manual_present",
        reason: "Not allowed",
      }),
    ).toThrowError(new ManualAttendanceError("not_owner"));
  });

  it("returns the enrolled roster with current status", () => {
    setManualAttendance(database.db, {
      lecturerId: DEMO.lecturerId,
      classSessionId: DEMO.classSessionId,
      studentId: DEMO.enrolledStudentIds[0],
      status: "manual_present",
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
