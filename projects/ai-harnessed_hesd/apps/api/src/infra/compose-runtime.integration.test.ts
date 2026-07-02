import { execFile } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { describe, expect, it } from "vitest";
import pg from "pg";
import { createClient } from "redis";

const execFileAsync = promisify(execFile);
const REPO_ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../../../..");

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const redisUrl = process.env.REDIS_URL ?? process.env.TEST_REDIS_URL;

describe("compose test stack connectivity — FR-07 FR-16 AC-01 AC-11 NFR-16", () => {
  it("postgres is reachable for session and check-in persistence prerequisites", async () => {
    expect(databaseUrl, "DATABASE_URL must be set by harness test stack").toBeTruthy();

    const client = new pg.Client({ connectionString: databaseUrl });
    await client.connect();
    const result = await client.query<{ ok: number }>("SELECT 1 AS ok");
    expect(result.rows[0]?.ok).toBe(1);
    await client.end();
  });

  it("redis is reachable for QR rotation and cache-backed workflows", async () => {
    expect(redisUrl, "REDIS_URL must be set by harness test stack").toBeTruthy();

    const client = createClient({ url: redisUrl });
    client.on("error", () => undefined);
    await client.connect();
    const pong = await client.ping();
    expect(pong).toBe("PONG");
    await client.quit();
  });

  it("migrate hook records baseline schema bookkeeping on test database", async () => {
    expect(databaseUrl).toBeTruthy();

    await execFileAsync("node", ["scripts/db-migrate.mjs"], {
      cwd: REPO_ROOT,
      env: { ...process.env, DATABASE_URL: databaseUrl! },
    });

    const client = new pg.Client({ connectionString: databaseUrl });
    await client.connect();
    const result = await client.query<{ id: string }>(
      "SELECT id FROM _attendly_schema_migrations WHERE id = $1",
      ["infra-local-runtime-compose-baseline"],
    );
    expect(result.rowCount).toBe(1);
    await client.end();
  });
});
