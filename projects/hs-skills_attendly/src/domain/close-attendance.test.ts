import { eq } from "drizzle-orm";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createDatabase } from "../db/client";
import { DEMO, seedDatabase } from "../db/seed";
import {
  attendanceRecords,
  classSessions,
  checkInAttempts,
} from "../db/schema";
import { checkIn } from "./check-in";
import {
  closeAttendance,
  CloseAttendanceError,
} from "./close-attendance";
import { clearActiveQrCache, openAttendance } from "./qr-session";

describe("close attendance", () => {
  let database: ReturnType<typeof createDatabase>;
  const now = new Date("2026-07-18T08:30:00Z");

  beforeEach(() => {
    database = createDatabase(":memory:");
    seedDatabase(database.db, database.sqlite);
    clearActiveQrCache();
  });

  afterEach(() => database.sqlite.close());

  it("marks every enrolled student without a record Absent", () => {
    const result = closeAttendance(
      database.db,
      DEMO.classSessionId,
      DEMO.lecturerId,
      now,
    );
    const records = database.db.select().from(attendanceRecords).all();
    const session = database.db
      .select()
      .from(classSessions)
      .where(eq(classSessions.id, DEMO.classSessionId))
      .get();

    expect(result).toEqual({
      absentCount: DEMO.enrolledStudentIds.length,
      closedAt: now,
    });
    expect(records).toHaveLength(DEMO.enrolledStudentIds.length);
    expect(records.map(({ studentId }) => studentId)).toEqual(
      expect.arrayContaining([...DEMO.enrolledStudentIds]),
    );
    expect(
      records.every(
        ({ status, method }) => status === "absent" && method === "system",
      ),
    ).toBe(true);
    expect(
      records.some(({ studentId }) => studentId === DEMO.nonEnrolledStudentId),
    ).toBe(false);
    expect(session?.attendanceClosedAt).toEqual(now);
  });

  it.each(["present", "late", "manual_present", "excused"] as const)(
    "preserves an existing %s record",
    (status) => {
      database.db
        .insert(attendanceRecords)
        .values({
          id: `existing-${status}`,
          studentId: DEMO.enrolledStudentIds[0],
          classSessionId: DEMO.classSessionId,
          status,
          method: status === "present" ? "qr" : "manual",
          checkedInAt: new Date(now.getTime() - 60_000),
          createdAt: new Date(now.getTime() - 60_000),
        })
        .run();

      const result = closeAttendance(
        database.db,
        DEMO.classSessionId,
        DEMO.lecturerId,
        now,
      );
      const records = database.db.select().from(attendanceRecords).all();

      expect(result.absentCount).toBe(1);
      expect(
        records.find(
          ({ studentId }) => studentId === DEMO.enrolledStudentIds[0],
        )?.status,
      ).toBe(status);
      expect(
        records.find(
          ({ studentId }) => studentId === DEMO.enrolledStudentIds[1],
        )?.status,
      ).toBe("absent");
    },
  );

  it("rejects further QR check-in after closing", () => {
    const openedAt = new Date(now.getTime() - 1_000);
    const qr = openAttendance(
      database.db,
      DEMO.classSessionId,
      DEMO.lecturerId,
      openedAt,
    );
    closeAttendance(
      database.db,
      DEMO.classSessionId,
      DEMO.lecturerId,
      now,
    );

    expect(
      checkIn(database.db, {
        studentId: DEMO.enrolledStudentIds[0],
        classSessionId: DEMO.classSessionId,
        token: qr.token,
        now: new Date(now.getTime() + 1_000),
      }),
    ).toEqual({ ok: false, reason: "attendance_not_open" });
    expect(database.db.select().from(checkInAttempts).get()?.reason).toBe(
      "attendance_not_open",
    );
  });

  it("requires the owning lecturer and an existing session", () => {
    expect(() =>
      closeAttendance(
        database.db,
        DEMO.classSessionId,
        DEMO.enrolledStudentIds[0],
        now,
      ),
    ).toThrowError(new CloseAttendanceError("not_owner"));
    expect(() =>
      closeAttendance(
        database.db,
        "missing-session",
        DEMO.lecturerId,
        now,
      ),
    ).toThrowError(new CloseAttendanceError("session_not_found"));
  });
});
