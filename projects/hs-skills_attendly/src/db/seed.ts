import type Database from "better-sqlite3";
import { scryptSync } from "node:crypto";
import { createDatabase, type AttendlyDatabase } from "./client";
import { createSchema } from "./migrate";
import {
  attendanceRecords,
  classSections,
  classSessions,
  enrollments,
  users,
} from "./schema";

export const DEMO = {
  password: "attendly-demo",
  lecturerId: "lecturer-ada",
  enrolledStudentIds: ["student-linh", "student-minh"],
  nonEnrolledStudentId: "student-an",
  classSectionId: "section-ai-101",
  classSessionId: "session-ai-101-01",
  pastSessionIds: ["session-ai-101-past-1", "session-ai-101-past-2"],
  presentWindowMinutes: 10,
  lateWindowMinutes: 20,
} as const;

function demoPasswordHash(password: string) {
  const salt = "attendly-demo-salt";
  return `scrypt:${salt}:${scryptSync(password, salt, 64).toString("hex")}`;
}

export function seedDatabase(db: AttendlyDatabase, sqlite: Database.Database) {
  sqlite.exec(`
    DROP TABLE IF EXISTS audit_logs;
    DROP TABLE IF EXISTS attendance_records;
    DROP TABLE IF EXISTS check_in_attempts;
    DROP TABLE IF EXISTS qr_session_tokens;
    DROP TABLE IF EXISTS class_sessions;
    DROP TABLE IF EXISTS enrollments;
    DROP TABLE IF EXISTS class_sections;
    DROP TABLE IF EXISTS users;
  `);
  createSchema(sqlite);
  const now = new Date();
  const passwordHash = demoPasswordHash(DEMO.password);

  sqlite.transaction(() => {
    db.insert(users)
      .values([
        {
          id: DEMO.lecturerId,
          email: "ada@attendly.test",
          name: "Dr. Ada",
          role: "lecturer",
          passwordHash,
          createdAt: now,
        },
        {
          id: DEMO.enrolledStudentIds[0],
          email: "linh@attendly.test",
          name: "Linh",
          role: "student",
          passwordHash,
          createdAt: now,
        },
        {
          id: DEMO.enrolledStudentIds[1],
          email: "minh@attendly.test",
          name: "Minh",
          role: "student",
          passwordHash,
          createdAt: now,
        },
        {
          id: DEMO.nonEnrolledStudentId,
          email: "an@attendly.test",
          name: "An",
          role: "student",
          passwordHash,
          createdAt: now,
        },
      ])
      .run();

    db.insert(classSections)
      .values({
        id: DEMO.classSectionId,
        name: "AI Engineering 101",
        lecturerId: DEMO.lecturerId,
        presentWindowMinutes: DEMO.presentWindowMinutes,
        lateWindowMinutes: DEMO.lateWindowMinutes,
        createdAt: now,
      })
      .run();

    db.insert(enrollments)
      .values(
        DEMO.enrolledStudentIds.map((studentId, index) => ({
          id: `enrollment-${index + 1}`,
          classSectionId: DEMO.classSectionId,
          studentId,
          createdAt: now,
        })),
      )
      .run();

    db.insert(classSessions)
      .values({
        id: DEMO.classSessionId,
        classSectionId: DEMO.classSectionId,
        startsAt: now,
        createdAt: now,
      })
      .run();
  })();
}

// Two closed past sessions with mixed resolved statuses so the reporting
// views have something to show from seed alone. Kept separate from
// seedDatabase so tests that assume an empty attendance table still hold.
export function seedAttendanceHistory(
  db: AttendlyDatabase,
  now = new Date(),
) {
  const dayMs = 24 * 60 * 60 * 1000;
  const pastSessions = DEMO.pastSessionIds.map((id, index) => {
    const startsAt = new Date(now.getTime() - (index + 1) * 7 * dayMs);
    return {
      id,
      startsAt,
      openedAt: startsAt,
      closedAt: new Date(startsAt.getTime() + 60 * 60 * 1000),
    };
  });

  db.insert(classSessions)
    .values(
      pastSessions.map((session) => ({
        id: session.id,
        classSectionId: DEMO.classSectionId,
        startsAt: session.startsAt,
        attendanceOpenedAt: session.openedAt,
        attendanceClosedAt: session.closedAt,
        createdAt: session.openedAt,
      })),
    )
    .run();

  const [linh, minh] = DEMO.enrolledStudentIds;
  const [lastWeek, twoWeeksAgo] = pastSessions;
  db.insert(attendanceRecords)
    .values([
      {
        id: "attendance-linh-past-1",
        studentId: linh,
        classSessionId: lastWeek.id,
        status: "present",
        method: "qr",
        checkedInAt: new Date(lastWeek.openedAt.getTime() + 5 * 60 * 1000),
        createdAt: lastWeek.openedAt,
      },
      {
        id: "attendance-minh-past-1",
        studentId: minh,
        classSessionId: lastWeek.id,
        status: "absent",
        method: "system",
        checkedInAt: lastWeek.closedAt,
        createdAt: lastWeek.closedAt,
      },
      {
        id: "attendance-linh-past-2",
        studentId: linh,
        classSessionId: twoWeeksAgo.id,
        status: "late",
        method: "qr",
        checkedInAt: new Date(twoWeeksAgo.openedAt.getTime() + 15 * 60 * 1000),
        createdAt: twoWeeksAgo.openedAt,
      },
      {
        id: "attendance-minh-past-2",
        studentId: minh,
        classSessionId: twoWeeksAgo.id,
        status: "excused",
        method: "manual",
        checkedInAt: twoWeeksAgo.closedAt,
        createdAt: twoWeeksAgo.closedAt,
      },
    ])
    .run();
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { db, sqlite } = createDatabase();
  seedDatabase(db, sqlite);
  seedAttendanceHistory(db);
  sqlite.close();
  console.log("Seeded Attendly demo data.");
}
