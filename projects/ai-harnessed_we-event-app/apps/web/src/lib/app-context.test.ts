import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { organizerNavItems, participantNavItems, roleLabel } from "./app-context.js";

describe("app context", () => {
  it("labels roles for the top bar", () => {
    assert.equal(roleLabel("participant"), "Participant");
    assert.equal(roleLabel("organizer-admin"), "Organizer Admin");
    assert.equal(roleLabel("organizer-staff"), "Organizer Staff");
  });

  it("scopes navigation items to roles", () => {
    assert.ok(participantNavItems.every((item) => item.roles.includes("participant")));
    assert.ok(
      organizerNavItems.some(
        (item) => item.roles.includes("organizer-admin") && item.href.includes("audit"),
      ),
    );
  });
});
