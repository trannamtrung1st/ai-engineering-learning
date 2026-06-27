import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { sessionDisplayName } from "./session-display-name.js";

describe("sessionDisplayName (FR-32, FR-33, NFR-07)", () => {
  it("prefers displayName over email and actorId", () => {
    assert.equal(
      sessionDisplayName({
        displayName: "Alex Rivera",
        email: "alex@example.com",
        actorId: "00000000-0000-0000-0000-000000000001",
        role: "Participant",
        assignedEventIds: [],
      }),
      "Alex Rivera",
    );
  });

  it("falls back to email when displayName is missing", () => {
    assert.equal(
      sessionDisplayName({
        email: "alex@example.com",
        actorId: "00000000-0000-0000-0000-000000000001",
        role: "Participant",
        assignedEventIds: [],
      }),
      "alex@example.com",
    );
  });

  it("never exposes actorId in chrome label", () => {
    const label = sessionDisplayName({
      actorId: "participant-1",
      role: "Participant",
      assignedEventIds: [],
    });
    assert.equal(label, "Signed in user");
    assert.doesNotMatch(label, /participant-1/);
  });
});
