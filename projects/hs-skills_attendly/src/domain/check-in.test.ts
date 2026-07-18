import { eq } from "drizzle-orm";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createDatabase } from "../db/client";
import { DEMO, seedDatabase } from "../db/seed";
import {
  attendanceRecords,
  checkInAttempts,
  classSessions,
  qrSessionTokens,
} from "../db/schema";
import { checkIn } from "./check-in";
import { clearActiveQrCache, openAttendance } from "./qr-session";

describe("student check-in", () => {
  let database: ReturnType<typeof createDatabase>;
  const now = new Date("2026-07-18T08:00:00Z");

  beforeEach(() => {
    database = createDatabase(":memory:");
    seedDatabase(database.db, database.sqlite);
    clearActiveQrCache();
  });

  afterEach(() => database.sqlite.close());

  function open() {
    return openAttendance(
      database.db,
      DEMO.classSessionId,
      DEMO.lecturerId,
      now,
    );
  }

  function keepQrValidUntil(expiresAt: Date) {
    database.db.update(qrSessionTokens).set({ expiresAt }).run();
  }

  it("allows two enrolled students to use the same valid token", () => {
    const qr = open();
    const results = DEMO.enrolledStudentIds.map((studentId) =>
      checkIn(database.db, {
        studentId,
        classSessionId: DEMO.classSessionId,
        token: qr.token,
        now: new Date(now.getTime() + 1_000),
      }),
    );

    expect(results.every((result) => result.ok)).toBe(true);
    expect(
      results.every((result) => result.ok && result.status === "present"),
    ).toBe(true);
    expect(database.db.select().from(attendanceRecords).all()).toHaveLength(2);
    expect(
      database.db
        .select()
        .from(checkInAttempts)
        .where(eq(checkInAttempts.outcome, "success"))
        .all(),
    ).toHaveLength(2);
  });

  it("records Late after the present window but inside the late window", () => {
    const qr = open();
    const checkInAt = new Date(
      now.getTime() + (DEMO.presentWindowMinutes + 1) * 60_000,
    );
    keepQrValidUntil(new Date(checkInAt.getTime() + 60_000));

    const result = checkIn(database.db, {
      studentId: DEMO.enrolledStudentIds[0],
      classSessionId: DEMO.classSessionId,
      token: qr.token,
      now: checkInAt,
    });

    expect(result).toMatchObject({ ok: true, status: "late" });
    expect(database.db.select().from(attendanceRecords).get()?.status).toBe(
      "late",
    );
  });

  it("treats the exact present-window endpoint as Present", () => {
    const qr = open();
    const checkInAt = new Date(
      now.getTime() + DEMO.presentWindowMinutes * 60_000,
    );
    keepQrValidUntil(new Date(checkInAt.getTime() + 60_000));

    const result = checkIn(database.db, {
      studentId: DEMO.enrolledStudentIds[0],
      classSessionId: DEMO.classSessionId,
      token: qr.token,
      now: checkInAt,
    });

    expect(result).toMatchObject({ ok: true, status: "present" });
  });

  it("treats the exact late-window endpoint as Late", () => {
    const qr = open();
    const checkInAt = new Date(
      now.getTime() +
        (DEMO.presentWindowMinutes + DEMO.lateWindowMinutes) * 60_000,
    );
    keepQrValidUntil(new Date(checkInAt.getTime() + 60_000));

    const result = checkIn(database.db, {
      studentId: DEMO.enrolledStudentIds[0],
      classSessionId: DEMO.classSessionId,
      token: qr.token,
      now: checkInAt,
    });

    expect(result).toMatchObject({ ok: true, status: "late" });
  });

  it("rejects and logs check-in after both attendance windows", () => {
    const qr = open();
    const checkInAt = new Date(
      now.getTime() +
        (DEMO.presentWindowMinutes + DEMO.lateWindowMinutes) * 60_000 +
        1,
    );
    keepQrValidUntil(new Date(checkInAt.getTime() + 60_000));

    const result = checkIn(database.db, {
      studentId: DEMO.enrolledStudentIds[0],
      classSessionId: DEMO.classSessionId,
      token: qr.token,
      now: checkInAt,
    });

    expect(result).toEqual({
      ok: false,
      reason: "outside_attendance_windows",
    });
    expect(database.db.select().from(attendanceRecords).get()).toBeUndefined();
    expect(database.db.select().from(checkInAttempts).get()?.reason).toBe(
      "outside_attendance_windows",
    );
  });

  it("rejects and logs a non-enrolled student", () => {
    const qr = open();
    const result = checkIn(database.db, {
      studentId: DEMO.nonEnrolledStudentId,
      classSessionId: DEMO.classSessionId,
      token: qr.token,
      now: new Date(now.getTime() + 1_000),
    });

    expect(result).toEqual({ ok: false, reason: "not_enrolled" });
    expect(database.db.select().from(checkInAttempts).get()?.reason).toBe(
      "not_enrolled",
    );
  });

  it("rejects and logs a duplicate successful check-in", () => {
    const qr = open();
    const input = {
      studentId: DEMO.enrolledStudentIds[0],
      classSessionId: DEMO.classSessionId,
      token: qr.token,
      now: new Date(now.getTime() + 1_000),
    };

    expect(checkIn(database.db, input).ok).toBe(true);
    expect(checkIn(database.db, input)).toEqual({
      ok: false,
      reason: "already_checked_in",
    });
    expect(database.db.select().from(attendanceRecords).all()).toHaveLength(1);
    expect(database.db.select().from(checkInAttempts).all()).toHaveLength(2);
  });

  it("rejects expired and invalid tokens with specific reasons", () => {
    const qr = open();
    expect(
      checkIn(database.db, {
        studentId: DEMO.enrolledStudentIds[0],
        classSessionId: DEMO.classSessionId,
        token: qr.token,
        now: new Date(now.getTime() + 30_001),
      }),
    ).toEqual({ ok: false, reason: "expired_token" });
    expect(
      checkIn(database.db, {
        studentId: DEMO.enrolledStudentIds[0],
        classSessionId: DEMO.classSessionId,
        token: "not-a-token",
        now,
      }),
    ).toEqual({ ok: false, reason: "invalid_token" });
  });

  it("rejects a valid token submitted for another open session", () => {
    const qr = open();
    const otherSessionId = "session-ai-101-02";
    database.db
      .insert(classSessions)
      .values({
        id: otherSessionId,
        classSectionId: DEMO.classSectionId,
        startsAt: now,
        attendanceOpenedAt: now,
        createdAt: now,
      })
      .run();

    expect(
      checkIn(database.db, {
        studentId: DEMO.enrolledStudentIds[0],
        classSessionId: otherSessionId,
        token: qr.token,
        now,
      }),
    ).toEqual({ ok: false, reason: "wrong_session" });
  });

  it("rejects and logs a check-in before attendance opens", () => {
    const result = checkIn(database.db, {
      studentId: DEMO.enrolledStudentIds[0],
      classSessionId: DEMO.classSessionId,
      token: "unopened",
      now,
    });

    expect(result).toEqual({ ok: false, reason: "attendance_not_open" });
    expect(database.db.select().from(checkInAttempts).all()).toHaveLength(1);
  });
});
