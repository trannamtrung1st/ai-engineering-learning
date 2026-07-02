#!/usr/bin/env node
/**
 * Baseline seed hook for local Docker runtime.
 * Full fixtures (term/course/section/session) ship in infra-database-migrations slice.
 */
import pg from "pg";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;

if (!databaseUrl) {
  console.error("db:seed — DATABASE_URL or TEST_DATABASE_URL is required");
  process.exit(1);
}

if (process.env.SEED_ENABLED === "false") {
  console.log("db:seed — skipped (SEED_ENABLED=false)");
  process.exit(0);
}

const client = new pg.Client({ connectionString: databaseUrl });

try {
  await client.connect();
  await client.query(`
    CREATE TABLE IF NOT EXISTS _attendly_seed_runs (
      id text PRIMARY KEY,
      seeded_at timestamptz NOT NULL DEFAULT now()
    )
  `);
  await client.query(
    `
    INSERT INTO _attendly_seed_runs (id)
    VALUES ($1)
    ON CONFLICT (id) DO NOTHING
    `,
    ["infra-local-runtime-compose-baseline"],
  );
  console.log("db:seed — baseline seed bookkeeping applied (fixtures pending migrations slice)");
} catch (error) {
  console.error("db:seed — failed:", error);
  process.exit(1);
} finally {
  await client.end().catch(() => undefined);
}
