#!/usr/bin/env node
/**
 * Baseline migration hook for local Docker runtime.
 * Creates schema bookkeeping table; domain migrations land in infra-database-migrations slice.
 */
import pg from "pg";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;

if (!databaseUrl) {
  console.error("db:migrate — DATABASE_URL or TEST_DATABASE_URL is required");
  process.exit(1);
}

const client = new pg.Client({ connectionString: databaseUrl });

try {
  await client.connect();
  await client.query(`
    CREATE TABLE IF NOT EXISTS _attendly_schema_migrations (
      id text PRIMARY KEY,
      applied_at timestamptz NOT NULL DEFAULT now()
    )
  `);
  await client.query(
    `
    INSERT INTO _attendly_schema_migrations (id)
    VALUES ($1)
    ON CONFLICT (id) DO NOTHING
    `,
    ["infra-local-runtime-compose-baseline"],
  );
  console.log("db:migrate — baseline schema bookkeeping applied");
} catch (error) {
  console.error("db:migrate — failed:", error);
  process.exit(1);
} finally {
  await client.end().catch(() => undefined);
}
