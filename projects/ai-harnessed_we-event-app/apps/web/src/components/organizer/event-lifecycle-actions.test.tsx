import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { availableActions } from "./event-lifecycle-actions.js";

describe("availableActions", () => {
  it("FR-04: exposes Publish for Draft events", () => {
    const actions = availableActions("Draft", false);
    assert.ok(actions.some((action) => action.id === "publish" && action.label === "Publish"));
  });

  it("FR-04: exposes Open registration for Published events", () => {
    const actions = availableActions("Published", false);
    assert.ok(
      actions.some((action) => action.id === "open-registration" && action.label === "Open registration"),
    );
  });

  it("FR-04: exposes pause and close during RegistrationOpen", () => {
    const actions = availableActions("RegistrationOpen", false);
    assert.ok(actions.some((action) => action.id === "pause"));
    assert.ok(actions.some((action) => action.id === "close-registration"));
  });

  it("FR-04: hides pause and close when registration already paused", () => {
    const actions = availableActions("RegistrationOpen", true);
    assert.ok(!actions.some((action) => action.id === "pause"));
    assert.ok(!actions.some((action) => action.id === "close-registration"));
    assert.ok(actions.some((action) => action.id === "cancel"));
  });

  it("FR-04: exposes Start for RegistrationClosed and Complete for InProgress", () => {
    assert.ok(
      availableActions("RegistrationClosed", false).some((action) => action.id === "start"),
    );
    assert.ok(
      availableActions("InProgress", false).some((action) => action.id === "complete"),
    );
  });
});
