import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";
import { closeDb, initDb } from "../db/pool.js";
import {
  ensureIdempotencySchema,
  executeIdempotent,
} from "./index.js";

const ACTOR_ID = "00000000-0000-0000-0000-000000000088";

describe("idempotency", () => {
  before(async () => {
    const databaseUrl =
      process.env.DATABASE_URL ??
      "postgresql://we_event:we_event@localhost:5432/we_event";
    await initDb(databaseUrl);
    await ensureIdempotencySchema();
  });

  after(async () => {
    await closeDb();
  });

  it("replays cached response for the same idempotency key and fingerprint", async () => {
    const key = randomUUID();
    const scope = `test.replay:${randomUUID()}`;
    const fingerprint = JSON.stringify({ action: "register" });
    let executions = 0;

    const headers = { "idempotency-key": key };

    const first = await executeIdempotent(
      headers,
      ACTOR_ID,
      scope,
      fingerprint,
      async () => {
        executions += 1;
        return { registrationId: randomUUID(), state: "Registered" };
      },
    );

    const second = await executeIdempotent(
      headers,
      ACTOR_ID,
      scope,
      fingerprint,
      async () => {
        executions += 1;
        return { registrationId: randomUUID(), state: "Registered" };
      },
    );

    assert.equal(executions, 1);
    assert.deepEqual(second, first);
  });
});
