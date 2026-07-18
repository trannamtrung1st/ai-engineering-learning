import { and, eq } from "drizzle-orm";
import { randomUUID } from "node:crypto";
import type { AttendlyDatabase } from "../db/client";
import {
  attendanceRecords,
  checkInAttempts,
  classSections,
  classSessions,
  enrollments,
  qrSessionTokens,
} from "../db/schema";
import { hashQrToken } from "./qr-session";

export type CheckInRejection =
  | "attendance_not_open"
  | "invalid_token"
  | "expired_token"
  | "wrong_session"
  | "not_enrolled"
  | "outside_attendance_windows"
  | "already_checked_in";

export type CheckInResult =
  | {
      ok: true;
      attendanceRecordId: string;
      status: "present" | "late";
    }
  | { ok: false; reason: CheckInRejection };

function recordAttempt(
  db: AttendlyDatabase,
  input: {
    studentId: string;
    classSessionId: string | null;
    tokenHash: string;
    outcome: "success" | "rejected";
    reason?: CheckInRejection;
    now: Date;
  },
) {
  db.insert(checkInAttempts)
    .values({
      id: randomUUID(),
      studentId: input.studentId,
      classSessionId: input.classSessionId,
      tokenHash: input.tokenHash,
      outcome: input.outcome,
      reason: input.reason,
      createdAt: input.now,
    })
    .run();
}

export function checkIn(
  db: AttendlyDatabase,
  input: {
    studentId: string;
    classSessionId: string;
    token: string;
    now?: Date;
  },
): CheckInResult {
  const now = input.now ?? new Date();
  const tokenHash = hashQrToken(input.token);
  const session = db
    .select()
    .from(classSessions)
    .where(eq(classSessions.id, input.classSessionId))
    .get();

  const reject = (
    reason: CheckInRejection,
    attemptedSessionId: string | null = session?.id ?? null,
  ): CheckInResult => {
    recordAttempt(db, {
      studentId: input.studentId,
      classSessionId: attemptedSessionId,
      tokenHash,
      outcome: "rejected",
      reason,
      now,
    });
    return { ok: false, reason };
  };

  if (
    !session ||
    !session.attendanceOpenedAt ||
    session.attendanceClosedAt
  ) {
    return reject("attendance_not_open");
  }

  const token = db
    .select()
    .from(qrSessionTokens)
    .where(eq(qrSessionTokens.tokenHash, tokenHash))
    .get();
  if (!token) return reject("invalid_token");
  if (token.classSessionId !== input.classSessionId) {
    return reject("wrong_session");
  }
  if (token.expiresAt.getTime() <= now.getTime()) {
    return reject("expired_token");
  }

  const section = db
    .select({
      presentWindowMinutes: classSections.presentWindowMinutes,
      lateWindowMinutes: classSections.lateWindowMinutes,
    })
    .from(classSections)
    .where(eq(classSections.id, session.classSectionId))
    .get();
  if (!section) return reject("attendance_not_open");

  const presentWindowEndsAt =
    session.attendanceOpenedAt.getTime() +
    section.presentWindowMinutes * 60_000;
  const lateWindowEndsAt =
    presentWindowEndsAt + section.lateWindowMinutes * 60_000;
  const status =
    now.getTime() <= presentWindowEndsAt
      ? "present"
      : now.getTime() <= lateWindowEndsAt
        ? "late"
        : null;
  if (!status) return reject("outside_attendance_windows");

  const enrollment = db
    .select({ id: enrollments.id })
    .from(enrollments)
    .where(
      and(
        eq(enrollments.classSectionId, session.classSectionId),
        eq(enrollments.studentId, input.studentId),
      ),
    )
    .get();
  if (!enrollment) return reject("not_enrolled");

  const existing = db
    .select({ id: attendanceRecords.id })
    .from(attendanceRecords)
    .where(
      and(
        eq(attendanceRecords.classSessionId, input.classSessionId),
        eq(attendanceRecords.studentId, input.studentId),
      ),
    )
    .get();
  if (existing) return reject("already_checked_in");

  const attendanceRecordId = randomUUID();
  try {
    db.transaction((tx) => {
      tx.insert(attendanceRecords)
        .values({
          id: attendanceRecordId,
          studentId: input.studentId,
          classSessionId: input.classSessionId,
          status,
          method: "qr",
          checkedInAt: now,
          createdAt: now,
        })
        .run();
      tx.insert(checkInAttempts)
        .values({
          id: randomUUID(),
          studentId: input.studentId,
          classSessionId: input.classSessionId,
          tokenHash,
          outcome: "success",
          createdAt: now,
        })
        .run();
    });
  } catch (error) {
    // A concurrent submit can pass the duplicate check above and then lose the
    // race to the unique (classSessionId, studentId) index — treat that as a
    // clean "already checked in" instead of surfacing a 500.
    if (isUniqueViolation(error)) return reject("already_checked_in");
    throw error;
  }

  return { ok: true, attendanceRecordId, status };
}

function isUniqueViolation(error: unknown) {
  return (
    error instanceof Error &&
    /UNIQUE constraint failed/i.test(error.message)
  );
}
