import { eq } from "drizzle-orm";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createDatabase } from "../db/client";
import { DEMO, seedDatabase } from "../db/seed";
import {
  attendanceRecords,
  checkInAttempts,
  classSessions,
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
    expect(database.db.select().from(attendanceRecords).all()).toHaveLength(2);
    expect(
      database.db
        .select()
        .from(checkInAttempts)
        .where(eq(checkInAttempts.outcome, "success"))
        .all(),
    ).toHaveLength(2);
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
