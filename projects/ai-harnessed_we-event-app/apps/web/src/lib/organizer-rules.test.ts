import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  canAccessEvent,
  filterEventsForScope,
  isOrganizerAdmin,
  isOrganizerStaff,
} from "./organizer-rules.js";
import type { SessionInfo } from "./participant-api.js";

const adminSession: SessionInfo = {
  actorId: "admin-1",
  role: "OrganizerAdmin",
  assignedEventIds: [],
};

const staffSession: SessionInfo = {
  actorId: "staff-1",
  role: "OrganizerStaff",
  assignedEventIds: ["evt-a", "evt-b"],
};

describe("organizer scope rules", () => {
  describe("FR-30: role and event scope", () => {
    it("identifies organizer admin and staff roles", () => {
      assert.equal(isOrganizerAdmin(adminSession), true);
      assert.equal(isOrganizerStaff(adminSession), false);
      assert.equal(isOrganizerStaff(staffSession), true);
      assert.equal(isOrganizerAdmin(staffSession), false);
    });

    it("allows admin access to any event", () => {
      assert.equal(canAccessEvent(adminSession, "evt-unknown"), true);
    });

    it("restricts staff to assigned event ids only", () => {
      assert.equal(canAccessEvent(staffSession, "evt-a"), true);
      assert.equal(canAccessEvent(staffSession, "evt-b"), true);
      assert.equal(canAccessEvent(staffSession, "evt-c"), false);
    });

    it("filters event lists to staff assignments", () => {
      const events = [
        { eventId: "evt-a", name: "A" },
        { eventId: "evt-b", name: "B" },
        { eventId: "evt-c", name: "C" },
      ];
      assert.deepEqual(filterEventsForScope(adminSession, events), events);
      assert.deepEqual(filterEventsForScope(staffSession, events), [
        { eventId: "evt-a", name: "A" },
        { eventId: "evt-b", name: "B" },
      ]);
    });
  });
});
