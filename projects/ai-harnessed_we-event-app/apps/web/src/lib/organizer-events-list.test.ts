import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  paginateLocally,
  matchesEventListFilters,
} from "./organizer-events-list.js";

describe("organizer events list helpers", () => {
  describe("FR-30: staff list pagination and filtering", () => {
    it("paginates items with correct envelope metadata", () => {
      const items = Array.from({ length: 25 }, (_, index) => `row-${index}`);
      const page1 = paginateLocally(items, 1, 10);
      assert.equal(page1.items.length, 10);
      assert.equal(page1.page, 1);
      assert.equal(page1.pageSize, 10);
      assert.equal(page1.total, 25);
      assert.equal(page1.totalPages, 3);

      const page3 = paginateLocally(items, 3, 10);
      assert.equal(page3.items.length, 5);
      assert.equal(page3.page, 3);
    });

    it("matches search and state filters for staff-scoped lists", () => {
      const event = {
        eventId: "evt-1",
        name: "We Event Summit",
        state: "RegistrationOpen" as const,
        startAt: "2026-06-15T10:00:00.000Z",
        location: "Main Hall",
      };
      assert.equal(matchesEventListFilters(event, { q: "summit" }), true);
      assert.equal(matchesEventListFilters(event, { q: "auditorium" }), false);
      assert.equal(
        matchesEventListFilters(event, { state: "RegistrationOpen" }),
        true,
      );
      assert.equal(
        matchesEventListFilters(event, { state: "Draft" }),
        false,
      );
    });
  });
});
