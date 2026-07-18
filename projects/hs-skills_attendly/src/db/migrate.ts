import type Database from "better-sqlite3";

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
      present_window_minutes INTEGER NOT NULL,
      late_window_minutes INTEGER NOT NULL,
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
      status TEXT NOT NULL CHECK (status IN ('present', 'late', 'absent', 'excused', 'manual_present')),
      method TEXT NOT NULL CHECK (method IN ('qr', 'manual', 'system')),
      checked_in_at INTEGER NOT NULL,
      created_at INTEGER NOT NULL,
      UNIQUE(class_session_id, student_id)
    );
    CREATE TABLE IF NOT EXISTS audit_logs (
      id TEXT PRIMARY KEY,
      actor_id TEXT NOT NULL REFERENCES users(id),
      attendance_record_id TEXT REFERENCES attendance_records(id),
      action TEXT NOT NULL,
      old_value TEXT,
      new_value TEXT NOT NULL,
      reason TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
  `);
}

function hasColumn(sqlite: Database.Database, table: string, column: string) {
  const columns = sqlite
    .prepare(`PRAGMA table_info(${table})`)
    .all() as Array<{ name: string }>;
  return columns.some((info) => info.name === column);
}

function tableSql(sqlite: Database.Database, table: string) {
  const row = sqlite
    .prepare(
      "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
    )
    .get(table) as { sql?: string } | undefined;
  return row?.sql ?? "";
}

// Bring an existing database (e.g. one seeded by spec 001) up to the current
// schema without dropping data. Safe to run on every connection: it only
// changes anything when a column or CHECK constraint is actually missing.
export function migrateSchema(sqlite: Database.Database) {
  createSchema(sqlite);

  if (!hasColumn(sqlite, "class_sections", "present_window_minutes")) {
    sqlite.exec(
      "ALTER TABLE class_sections ADD COLUMN present_window_minutes INTEGER NOT NULL DEFAULT 0",
    );
  }
  if (!hasColumn(sqlite, "class_sections", "late_window_minutes")) {
    sqlite.exec(
      "ALTER TABLE class_sections ADD COLUMN late_window_minutes INTEGER NOT NULL DEFAULT 0",
    );
  }

  // Older databases created the attendance_records CHECK constraints before
  // the late/absent/excused statuses and the system method existed. SQLite
  // cannot alter a CHECK in place, so rebuild the table when it is stale.
  const attendanceSql = tableSql(sqlite, "attendance_records");
  if (attendanceSql && !attendanceSql.includes("'system'")) {
    sqlite.exec("PRAGMA foreign_keys = OFF");
    const rebuild = sqlite.transaction(() => {
      sqlite.exec(`
        ALTER TABLE attendance_records RENAME TO attendance_records_legacy;
        CREATE TABLE attendance_records (
          id TEXT PRIMARY KEY,
          student_id TEXT NOT NULL REFERENCES users(id),
          class_session_id TEXT NOT NULL REFERENCES class_sessions(id),
          status TEXT NOT NULL CHECK (status IN ('present', 'late', 'absent', 'excused', 'manual_present')),
          method TEXT NOT NULL CHECK (method IN ('qr', 'manual', 'system')),
          checked_in_at INTEGER NOT NULL,
          created_at INTEGER NOT NULL,
          UNIQUE(class_session_id, student_id)
        );
        INSERT INTO attendance_records
          SELECT id, student_id, class_session_id, status, method, checked_in_at, created_at
          FROM attendance_records_legacy;
        DROP TABLE attendance_records_legacy;
      `);
    });
    rebuild();
    sqlite.exec("PRAGMA foreign_keys = ON");
  }

  // Older databases created audit_logs with attendance_record_id NOT NULL,
  // but section-level events (e.g. report exports) have no single attendance
  // record. SQLite cannot drop NOT NULL in place, so rebuild when stale.
  const auditSql = tableSql(sqlite, "audit_logs");
  if (auditSql && auditSql.includes("attendance_record_id TEXT NOT NULL")) {
    sqlite.exec("PRAGMA foreign_keys = OFF");
    const rebuildAudit = sqlite.transaction(() => {
      sqlite.exec(`
        ALTER TABLE audit_logs RENAME TO audit_logs_legacy;
        CREATE TABLE audit_logs (
          id TEXT PRIMARY KEY,
          actor_id TEXT NOT NULL REFERENCES users(id),
          attendance_record_id TEXT REFERENCES attendance_records(id),
          action TEXT NOT NULL,
          old_value TEXT,
          new_value TEXT NOT NULL,
          reason TEXT NOT NULL,
          created_at INTEGER NOT NULL
        );
        INSERT INTO audit_logs
          SELECT id, actor_id, attendance_record_id, action, old_value, new_value, reason, created_at
          FROM audit_logs_legacy;
        DROP TABLE audit_logs_legacy;
      `);
    });
    rebuildAudit();
    sqlite.exec("PRAGMA foreign_keys = ON");
  }
}
