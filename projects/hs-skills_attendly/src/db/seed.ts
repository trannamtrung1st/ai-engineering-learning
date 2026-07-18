import type Database from "better-sqlite3";
import { scryptSync } from "node:crypto";
import { createDatabase, type AttendlyDatabase } from "./client";
import {
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
} as const;

function demoPasswordHash(password: string) {
  const salt = "attendly-demo-salt";
  return `scrypt:${salt}:${scryptSync(password, salt, 64).toString("hex")}`;
}

export function createSchema(sqlite: Database.Database) {
  sqlite.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      email TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      role TEXT NOT NULL CHECK (role IN ('student', 'lecturer')),
      password_hash TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS class_sections (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      lecturer_id TEXT NOT NULL REFERENCES users(id),
      created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS enrollments (
      id TEXT PRIMARY KEY,
      class_section_id TEXT NOT NULL REFERENCES class_sections(id),
      student_id TEXT NOT NULL REFERENCES users(id),
      created_at INTEGER NOT NULL,
      UNIQUE(class_section_id, student_id)
    );
    CREATE TABLE IF NOT EXISTS class_sessions (
      id TEXT PRIMARY KEY,
      class_section_id TEXT NOT NULL REFERENCES class_sections(id),
      starts_at INTEGER NOT NULL,
      attendance_opened_at INTEGER,
      attendance_closed_at INTEGER,
      created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS qr_session_tokens (
      id TEXT PRIMARY KEY,
      class_session_id TEXT NOT NULL REFERENCES class_sessions(id),
      token_hash TEXT NOT NULL,
      expires_at INTEGER NOT NULL,
      created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS check_in_attempts (
      id TEXT PRIMARY KEY,
      student_id TEXT NOT NULL REFERENCES users(id),
      class_session_id TEXT REFERENCES class_sessions(id),
      token_hash TEXT,
      outcome TEXT NOT NULL CHECK (outcome IN ('success', 'rejected')),
      reason TEXT,
      created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS attendance_records (
      id TEXT PRIMARY KEY,
      student_id TEXT NOT NULL REFERENCES users(id),
      class_session_id TEXT NOT NULL REFERENCES class_sessions(id),
      status TEXT NOT NULL CHECK (status IN ('present', 'manual_present')),
      method TEXT NOT NULL CHECK (method IN ('qr', 'manual')),
      checked_in_at INTEGER NOT NULL,
      created_at INTEGER NOT NULL,
      UNIQUE(class_session_id, student_id)
    );
    CREATE TABLE IF NOT EXISTS audit_logs (
      id TEXT PRIMARY KEY,
      actor_id TEXT NOT NULL REFERENCES users(id),
      attendance_record_id TEXT NOT NULL REFERENCES attendance_records(id),
      action TEXT NOT NULL,
      old_value TEXT,
      new_value TEXT NOT NULL,
      reason TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
  `);
}

export function seedDatabase(db: AttendlyDatabase, sqlite: Database.Database) {
  createSchema(sqlite);
  const now = new Date();
  const passwordHash = demoPasswordHash(DEMO.password);

  sqlite.transaction(() => {
    sqlite.exec(`
      DELETE FROM audit_logs;
      DELETE FROM attendance_records;
      DELETE FROM check_in_attempts;
      DELETE FROM qr_session_tokens;
      DELETE FROM class_sessions;
      DELETE FROM enrollments;
      DELETE FROM class_sections;
      DELETE FROM users;
    `);

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

if (import.meta.url === `file://${process.argv[1]}`) {
  const { db, sqlite } = createDatabase();
  seedDatabase(db, sqlite);
  sqlite.close();
  console.log("Seeded Attendly demo data.");
}
