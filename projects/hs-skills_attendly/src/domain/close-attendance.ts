import { eq } from "drizzle-orm";
import { randomUUID } from "node:crypto";
import type { AttendlyDatabase } from "../db/client";
import {
  attendanceRecords,
  classSections,
  classSessions,
  enrollments,
} from "../db/schema";

export class CloseAttendanceError extends Error {
  constructor(public readonly code: "session_not_found" | "not_owner") {
    super(code);
  }
}

export function closeAttendance(
  db: AttendlyDatabase,
  classSessionId: string,
  lecturerId: string,
  now = new Date(),
) {
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
    .where(eq(classSessions.id, classSessionId))
    .get();
  if (!session) throw new CloseAttendanceError("session_not_found");
  if (session.lecturerId !== lecturerId) {
    throw new CloseAttendanceError("not_owner");
  }

  return db.transaction((tx) => {
    tx.update(classSessions)
      .set({ attendanceClosedAt: now })
      .where(eq(classSessions.id, classSessionId))
      .run();

    const enrolledStudents = tx
      .select({ studentId: enrollments.studentId })
      .from(enrollments)
      .where(eq(enrollments.classSectionId, session.classSectionId))
      .all();
    const studentsWithRecords = new Set(
      tx
        .select({ studentId: attendanceRecords.studentId })
        .from(attendanceRecords)
        .where(eq(attendanceRecords.classSessionId, classSessionId))
        .all()
        .map(({ studentId }) => studentId),
    );

    let absentCount = 0;
    for (const { studentId } of enrolledStudents) {
      if (studentsWithRecords.has(studentId)) continue;

      tx.insert(attendanceRecords)
        .values({
          id: randomUUID(),
          studentId,
          classSessionId,
          status: "absent",
          method: "system",
          checkedInAt: now,
          createdAt: now,
        })
        .run();
      absentCount += 1;
    }

    return { absentCount, closedAt: now };
  });
}
