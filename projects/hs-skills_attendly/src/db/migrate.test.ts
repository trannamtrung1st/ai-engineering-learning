import Database from "better-sqlite3";
import { afterEach, describe, expect, it } from "vitest";
import { migrateSchema } from "./migrate";

describe("migrateSchema", () => {
  let sqlite: Database.Database;

  afterEach(() => sqlite.close());

  function columnNames(table: string) {
    return (
      sqlite.prepare(`PRAGMA table_info(${table})`).all() as Array<{
        name: string;
      }>
    ).map((info) => info.name);
  }

  function tableSql(table: string) {
    return (
      sqlite
        .prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name=?")
        .get(table) as { sql: string }
    ).sql;
  }

  it("initializes a full schema on an empty database", () => {
    sqlite = new Database(":memory:");

    migrateSchema(sqlite);

    expect(columnNames("class_sections")).toEqual(
      expect.arrayContaining(["present_window_minutes", "late_window_minutes"]),
    );
    const sql = tableSql("attendance_records");
    expect(sql).toContain("'absent'");
    expect(sql).toContain("'system'");
  });

  it("upgrades a spec-001 database without dropping data", () => {
    sqlite = new Database(":memory:");
    // Recreate the pre-002 shape: no policy columns, narrow CHECK constraints.
    sqlite.exec(`
      CREATE TABLE class_sections (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        lecturer_id TEXT NOT NULL,
        created_at INTEGER NOT NULL
      );
      CREATE TABLE attendance_records (
        id TEXT PRIMARY KEY,
        student_id TEXT NOT NULL,
        class_session_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('present', 'manual_present')),
        method TEXT NOT NULL CHECK (method IN ('qr', 'manual')),
        checked_in_at INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        UNIQUE(class_session_id, student_id)
      );
      INSERT INTO class_sections VALUES ('sec', 'Legacy', 'lec', 0);
      INSERT INTO attendance_records VALUES ('rec', 'stu', 'ses', 'present', 'qr', 0, 0);
    `);

    migrateSchema(sqlite);

    expect(columnNames("class_sections")).toEqual(
      expect.arrayContaining(["present_window_minutes", "late_window_minutes"]),
    );
    const preserved = sqlite
      .prepare("SELECT status FROM attendance_records WHERE id = 'rec'")
      .get() as { status: string };
    expect(preserved.status).toBe("present");
    // New statuses/methods now satisfy the rebuilt CHECK constraints.
    const sql = tableSql("attendance_records");
    expect(sql).toContain("'absent'");
    expect(sql).toContain("'system'");
  });

  it("is idempotent when run twice", () => {
    sqlite = new Database(":memory:");

    migrateSchema(sqlite);
    expect(() => migrateSchema(sqlite)).not.toThrow();
  });
});
