#!/usr/bin/env node
/**
 * Applies ordered SQL migrations from apps/api/db/migrations.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const MIGRATIONS_DIR = join(REPO_ROOT, "apps/api/db/migrations");

if (!databaseUrl) {
  console.error("db:migrate — DATABASE_URL or TEST_DATABASE_URL is required");
  process.exit(1);
}

function listMigrationFiles() {
  return readdirSync(MIGRATIONS_DIR)
    .filter((name) => name.endsWith(".sql"))
    .sort();
}

async function ensureBookkeepingTable(client) {
  await client.query(`
    CREATE TABLE IF NOT EXISTS _attendly_schema_migrations (
      id text PRIMARY KEY,
      applied_at timestamptz NOT NULL DEFAULT now()
    )
  `);
}

async function isMigrationApplied(client, migrationId) {
  const result = await client.query(
    "SELECT 1 FROM _attendly_schema_migrations WHERE id = $1",
    [migrationId],
  );
  return (result.rowCount ?? 0) > 0;
}

async function recordMigration(client, migrationId) {
  await client.query(
    `
    INSERT INTO _attendly_schema_migrations (id)
    VALUES ($1)
    ON CONFLICT (id) DO NOTHING
    `,
    [migrationId],
  );
}

async function applyMigrationFile(client, fileName) {
  const migrationId = fileName.replace(/\.sql$/, "");
  if (await isMigrationApplied(client, migrationId)) {
    console.log(`db:migrate — skip ${migrationId} (already applied)`);
    return;
  }

  const sql = readFileSync(join(MIGRATIONS_DIR, fileName), "utf8");
  await client.query("BEGIN");
  try {
    await client.query(sql);
    await recordMigration(client, migrationId);
    await client.query("COMMIT");
    console.log(`db:migrate — applied ${migrationId}`);
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  }
}

const client = new pg.Client({ connectionString: databaseUrl });

try {
  await client.connect();
  await ensureBookkeepingTable(client);

  // Backward compatibility with infra-local-runtime-compose baseline bookkeeping row.
  await recordMigration(client, "infra-local-runtime-compose-baseline");

  const files = listMigrationFiles();
  if (files.length === 0) {
    console.warn("db:migrate — no SQL files found in apps/api/db/migrations");
  }

  for (const fileName of files) {
    await applyMigrationFile(client, fileName);
  }

  console.log("db:migrate — complete");
} catch (error) {
  console.error("db:migrate — failed:", error);
  process.exit(1);
} finally {
  await client.end().catch(() => undefined);
}
