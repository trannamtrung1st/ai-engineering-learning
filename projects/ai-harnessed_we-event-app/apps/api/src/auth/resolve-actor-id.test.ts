import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { resolveActorId } from "./resolve-actor-id.js";

describe("resolveActorId", () => {
  it("returns seed organizer/staff UUIDs unchanged (version nibble may be 0)", () => {
    assert.equal(
      resolveActorId("00000000-0000-0000-0000-000000000098"),
      "00000000-0000-0000-0000-000000000098",
    );
    assert.equal(
      resolveActorId("00000000-0000-0000-0000-000000000099"),
      "00000000-0000-0000-0000-000000000099",
    );
  });

  it("maps dev participant subs to deterministic UUIDs", () => {
    assert.equal(
      resolveActorId("participant-1"),
      "8e7b79e2-4984-4f64-b15f-e3c760c73499",
    );
  });
});
