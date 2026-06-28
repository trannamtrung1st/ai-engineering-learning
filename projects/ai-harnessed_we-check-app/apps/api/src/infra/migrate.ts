import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { DbPool } from "./db.js";

const SQL_DIR = join(dirname(fileURLToPath(import.meta.url)), "../../sql");

const MIGRATION_FILES = [
  "001_foundation.sql",
  "002_user_audit.sql",
  "003_roster_enrollment.sql",
  "004_session_management.sql",
] as const;

export async function runMigrations(db: DbPool): Promise<void> {
  await db.query(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      version VARCHAR(128) PRIMARY KEY,
      applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  for (const file of MIGRATION_FILES) {
    const version = file.replace(/\.sql$/, "");
    const applied = await db.query<{ version: string }>(
      "SELECT version FROM schema_migrations WHERE version = $1",
      [version],
    );
    if (applied.rowCount && applied.rowCount > 0) {
      continue;
    }

    const sql = readFileSync(join(SQL_DIR, file), "utf8");
    await db.query("BEGIN");
    try {
      await db.query(sql);
      await db.query(
        "INSERT INTO schema_migrations (version) VALUES ($1)",
        [version],
      );
      await db.query("COMMIT");
    } catch (error) {
      await db.query("ROLLBACK");
      throw error;
    }
  }
}
