import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import pg from "pg";

/**
 * Traceability: NFR-02 NFR-04 FR-09 FR-07 BR-04 BR-11 BR-15 AC-09 AC-07 NFR-05 NFR-23
 * Cases: TC-NFR-02-005 TC-NFR-04-006 TC-NFR-04-003 TC-NFR-04-012 TC-NFR-04-005
 */
const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");
const COMPOSE_PATH = join(REPO_ROOT, "docker-compose.yml");
const DEFAULT_DATABASE_URL =
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";
const DATABASE_URL = process.env.DATABASE_URL ?? DEFAULT_DATABASE_URL;
const NFR04_LATENCY_BUDGET_MS = 2000;

function readComposeSpec(): string {
  return readFileSync(COMPOSE_PATH, "utf8");
}

async function withClient<T>(fn: (client: pg.Client) => Promise<T>): Promise<T> {
  const client = new pg.Client({ connectionString: DATABASE_URL });
  await client.connect();
  try {
    return await fn(client);
  } finally {
    await client.end();
  }
}

describe("docker-compose-db (NFR-02, NFR-04)", () => {
  describe("compose contract", () => {
    it("defines postgres:15-alpine db service with pg_isready healthcheck (NFR-02)", () => {
      const spec = readComposeSpec();
      assert.match(spec, /image:\s*postgres:15-alpine/);
      assert.match(spec, /POSTGRES_DB:\s*wecheck/);
      assert.match(spec, /POSTGRES_USER:\s*wecheck/);
      assert.match(spec, /POSTGRES_PASSWORD:\s*wecheck/);
      assert.match(spec, /5432:5432/);
      assert.match(spec, /pg_isready -U wecheck -d wecheck/);
    });

    it("documents local DATABASE_URL in .env.example (NFR-02)", () => {
      const envExample = readFileSync(join(REPO_ROOT, ".env.example"), "utf8");
      assert.match(
        envExample,
        /DATABASE_URL=postgresql:\/\/wecheck:wecheck@localhost:5432\/wecheck/,
      );
    });
  });

  describe("real PostgreSQL via Compose", () => {
    it("connects and reports PostgreSQL 15+ (TC-NFR-02-005, NFR-02)", async () => {
      await withClient(async (client) => {
        const result = await client.query<{ version: string }>(
          "SELECT version() AS version",
        );
        const version = result.rows[0]?.version ?? "";
        assert.match(version, /PostgreSQL 15\./);
      });
    });

    it("persists durable writes across reconnects, not process memory (TC-NFR-02-005, NFR-02 FR-09)", async () => {
      const tableName = `wecheck_public_${Date.now()}`;
      const marker = `marker-${Date.now()}`;

      await withClient(async (client) => {
        await client.query(
          `CREATE TABLE ${tableName} (id text PRIMARY KEY, note text NOT NULL)`,
        );
        await client.query(`INSERT INTO ${tableName} (id, note) VALUES ($1, $2)`, [
          marker,
          "NFR-02 durable write",
        ]);
      });

      await withClient(async (client) => {
        const row = await client.query<{ note: string }>(
          `SELECT note FROM ${tableName} WHERE id = $1`,
          [marker],
        );
        assert.equal(row.rowCount, 1);
        assert.equal(row.rows[0]?.note, "NFR-02 durable write");
        await client.query(`DROP TABLE IF EXISTS ${tableName}`);
      });
    });

    it("executes a simple query within NFR-04 latency budget (TC-NFR-04-006, NFR-04 FR-07)", async () => {
      const started = performance.now();
      await withClient(async (client) => {
        await client.query("SELECT 1 AS ok");
      });
      const elapsed = performance.now() - started;
      assert.ok(
        elapsed <= NFR04_LATENCY_BUDGET_MS,
        `expected query within ${NFR04_LATENCY_BUDGET_MS}ms, got ${elapsed.toFixed(1)}ms`,
      );
    });

    it("supports ACID transaction commit and rollback (NFR-02 FR-09 BR-04 BR-11 AC-09 AC-07 NFR-05 NFR-23)", async () => {
      const tableName = `wecheck_tx_${Date.now()}`;

      await withClient(async (client) => {
        await client.query(
          `CREATE TABLE ${tableName} (id text PRIMARY KEY, status text NOT NULL)`,
        );

        try {
          await client.query("BEGIN");
          await client.query(
            `INSERT INTO ${tableName} (id, status) VALUES ($1, $2)`,
            ["committed", "Present"],
          );
          await client.query("COMMIT");
        } catch (error) {
          await client.query("ROLLBACK");
          throw error;
        }

        try {
          await client.query("BEGIN");
          await client.query(
            `INSERT INTO ${tableName} (id, status) VALUES ($1, $2)`,
            ["rolled-back", "Pending"],
          );
          await client.query("ROLLBACK");
        } catch (error) {
          await client.query("ROLLBACK");
          throw error;
        }

        const rows = await client.query<{ id: string }>(
          `SELECT id FROM ${tableName} ORDER BY id`,
        );
        assert.deepEqual(
          rows.rows.map((row) => row.id),
          ["committed"],
        );
      });

      await withClient(async (client) => {
        await client.query(`DROP TABLE IF EXISTS ${tableName}`);
      });
    });
  });
});
