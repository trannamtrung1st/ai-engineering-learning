import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { after, before, describe, it } from "node:test";

import { checkDbHealth, closeDb, getPool, initDb } from "../db/pool.js";

const COMPOSE_DATABASE_URL =
  "postgresql://we_event:we_event@localhost:5432/we_event";

describe("docker-compose db runtime (NFR-02, NFR-04)", () => {
  before(async () => {
    process.env.DATABASE_URL ??= COMPOSE_DATABASE_URL;
    await initDb(process.env.DATABASE_URL);
  });

  after(async () => {
    await closeDb();
  });

  it("TC-NFR-02-012: integration tests connect to Compose Postgres not in-memory stores", async () => {
    assert.match(process.env.DATABASE_URL ?? "", /localhost:5432\/we_event/);
    assert.equal(await checkDbHealth(), true);

    const result = await getPool().query<{ version: string }>("SELECT version()");
    assert.match(result.rows[0]?.version ?? "", /PostgreSQL/i);
  });

  it("TC-NFR-04-013: transactional Postgres I/O is available for NFR-04 latency assertions", async () => {
    const started = performance.now();
    await getPool().query("SELECT 1");
    const elapsed = performance.now() - started;
    assert.ok(elapsed < 5000, "Compose Postgres round-trip should complete promptly");
  });

  it("docker-compose.yml defines healthy db service per local runtime policy", () => {
    const repoRoot = resolve(fileURLToPath(new URL(".", import.meta.url)), "../../../..");
    const compose = readFileSync(resolve(repoRoot, "docker-compose.yml"), "utf8");
    assert.match(compose, /postgres:16-alpine/);
    assert.match(compose, /POSTGRES_DB:\s*we_event/);
    assert.match(compose, /pg_isready -U we_event -d we_event/);
  });
});
