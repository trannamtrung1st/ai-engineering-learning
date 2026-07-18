import { and, eq } from "drizzle-orm";
import { randomUUID } from "node:crypto";
import type { AttendlyDatabase } from "../db/client";
import {
  attendanceRecords,
  auditLogs,
  classSections,
  classSessions,
  enrollments,
  users,
} from "../db/schema";

export type RosterEntry = {
  studentId: string;
  name: string;
  status: string | null;
};

export const MANUAL_ATTENDANCE_STATUSES = [
  "manual_present",
  "late",
  "absent",
  "excused",
] as const;

export type ManualAttendanceStatus =
  (typeof MANUAL_ATTENDANCE_STATUSES)[number];

export function isManualAttendanceStatus(
  value: unknown,
): value is ManualAttendanceStatus {
  return MANUAL_ATTENDANCE_STATUSES.some((status) => status === value);
}

export function getSessionRoster(
  db: AttendlyDatabase,
  classSessionId: string,
): RosterEntry[] {
  const session = db
    .select({ classSectionId: classSessions.classSectionId })
    .from(classSessions)
    .where(eq(classSessions.id, classSessionId))
    .get();
  if (!session) return [];

  return db
    .select({
      studentId: users.id,
      name: users.name,
      status: attendanceRecords.status,
    })
    .from(enrollments)
    .innerJoin(users, eq(enrollments.studentId, users.id))
    .leftJoin(
      attendanceRecords,
      and(
        eq(attendanceRecords.studentId, users.id),
        eq(attendanceRecords.classSessionId, classSessionId),
      ),
    )
    .where(eq(enrollments.classSectionId, session.classSectionId))
    .all();
}

export class ManualAttendanceError extends Error {
  constructor(
    public readonly code:
      | "invalid_reason"
      | "session_not_found"
      | "not_owner"
      | "not_enrolled",
  ) {
    super(code);
  }
}

export function setManualAttendance(
  db: AttendlyDatabase,
  input: {
    lecturerId: string;
    classSessionId: string;
    studentId: string;
    status: ManualAttendanceStatus;
    reason: string;
    now?: Date;
  },
) {
  const reason = input.reason.trim();
  if (!reason) throw new ManualAttendanceError("invalid_reason");
  const now = input.now ?? new Date();

  const session = db
    .select({
      id: classSessions.id,
      classSectionId: classSessions.classSectionId,
      lecturerId: classSections.lecturerId,
    })
    .from(classSessions)
    .innerJoin(
      classSections,
      eq(classSessions.classSectionId, classSections.id),
    )
    .where(eq(classSessions.id, input.classSessionId))
    .get();
  if (!session) throw new ManualAttendanceError("session_not_found");
  if (session.lecturerId !== input.lecturerId) {
    throw new ManualAttendanceError("not_owner");
  }

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
  if (!enrollment) throw new ManualAttendanceError("not_enrolled");

  return db.transaction((tx) => {
    const existing = tx
      .select()
      .from(attendanceRecords)
      .where(
        and(
          eq(attendanceRecords.classSessionId, input.classSessionId),
          eq(attendanceRecords.studentId, input.studentId),
        ),
      )
      .get();

    const attendanceRecordId = existing?.id ?? randomUUID();
    const oldValue = existing
      ? JSON.stringify({
          status: existing.status,
          method: existing.method,
          checkedInAt: existing.checkedInAt.toISOString(),
        })
      : null;
    const newValue = JSON.stringify({
      status: input.status,
      method: "manual",
      checkedInAt: now.toISOString(),
    });

    if (existing) {
      tx.update(attendanceRecords)
        .set({
          status: input.status,
          method: "manual",
          checkedInAt: now,
        })
        .where(eq(attendanceRecords.id, attendanceRecordId))
        .run();
    } else {
      tx.insert(attendanceRecords)
        .values({
          id: attendanceRecordId,
          studentId: input.studentId,
          classSessionId: input.classSessionId,
          status: input.status,
          method: "manual",
          checkedInAt: now,
          createdAt: now,
        })
        .run();
    }

    const auditLogId = randomUUID();
    tx.insert(auditLogs)
      .values({
        id: auditLogId,
        actorId: input.lecturerId,
        attendanceRecordId,
        action: "attendance.manual_set",
        oldValue,
        newValue,
        reason,
        createdAt: now,
      })
      .run();

    return { attendanceRecordId, auditLogId, status: input.status };
  });
}
