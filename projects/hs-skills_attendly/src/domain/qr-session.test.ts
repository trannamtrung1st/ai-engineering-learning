import { eq } from "drizzle-orm";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createDatabase } from "../db/client";
import { DEMO, seedDatabase } from "../db/seed";
import { classSessions, qrSessionTokens } from "../db/schema";
import {
  clearActiveQrCache,
  getCurrentQr,
  openAttendance,
  QrSessionError,
} from "./qr-session";

describe("QR attendance sessions", () => {
  let database: ReturnType<typeof createDatabase>;
  const openedAt = new Date("2026-07-18T08:00:00Z");

  beforeEach(() => {
    database = createDatabase(":memory:");
    seedDatabase(database.db, database.sqlite);
    clearActiveQrCache();
  });

  afterEach(() => database.sqlite.close());

  it("lets only the owning lecturer open attendance", () => {
    expect(() =>
      openAttendance(
        database.db,
        DEMO.classSessionId,
        DEMO.enrolledStudentIds[0],
        openedAt,
      ),
    ).toThrowError(new QrSessionError("not_owner"));

    const qr = openAttendance(
      database.db,
      DEMO.classSessionId,
      DEMO.lecturerId,
      openedAt,
    );
    const session = database.db
      .select()
      .from(classSessions)
      .where(eq(classSessions.id, DEMO.classSessionId))
      .get();

    expect(qr.expiresAt.getTime()).toBe(openedAt.getTime() + 30_000);
    expect(session?.attendanceOpenedAt).toEqual(openedAt);
  });

  it("keeps one token usable by multiple callers until its TTL", () => {
    const opened = openAttendance(
      database.db,
      DEMO.classSessionId,
      DEMO.lecturerId,
      openedAt,
    );
    const firstRead = getCurrentQr(
      database.db,
      DEMO.classSessionId,
      DEMO.lecturerId,
      new Date(openedAt.getTime() + 1_000),
    );
    const secondRead = getCurrentQr(
      database.db,
      DEMO.classSessionId,
      DEMO.lecturerId,
      new Date(openedAt.getTime() + 29_000),
    );

    expect(firstRead.token).toBe(opened.token);
    expect(secondRead.token).toBe(opened.token);
    expect(database.db.select().from(qrSessionTokens).all()).toHaveLength(1);
  });

  it("rotates the displayed token after expiry", () => {
    const first = openAttendance(
      database.db,
      DEMO.classSessionId,
      DEMO.lecturerId,
      openedAt,
    );
    const rotated = getCurrentQr(
      database.db,
      DEMO.classSessionId,
      DEMO.lecturerId,
      new Date(openedAt.getTime() + 30_001),
    );

    expect(rotated.token).not.toBe(first.token);
    expect(database.db.select().from(qrSessionTokens).all()).toHaveLength(2);
  });
});
