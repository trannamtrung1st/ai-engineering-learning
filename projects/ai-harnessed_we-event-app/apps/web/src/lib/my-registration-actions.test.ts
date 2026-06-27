import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { MyRegistrationListItem } from "@/lib/participant-api";

import { deriveMyRegistrationQuickActions } from "./my-registration-actions.js";

const OPEN = "2020-01-01T08:00:00.000Z";
const CLOSE = "2030-01-01T18:00:00.000Z";
const MID = new Date("2025-06-01T12:00:00.000Z").getTime();

function buildItem(
  overrides: Partial<MyRegistrationListItem> = {},
): MyRegistrationListItem {
  return {
    registrationId: "reg-1",
    eventId: "evt-1",
    eventName: "Summit",
    eventState: "Completed",
    state: "Attended",
    updatedAt: "2025-06-01T12:00:00.000Z",
    waitlistPosition: null,
    reasonText: null,
    checkinOpenAt: OPEN,
    checkinCloseAt: CLOSE,
    feedbackOpenAt: OPEN,
    feedbackCloseAt: CLOSE,
    selfCheckinEnabled: true,
    ...overrides,
  };
}

/** Traceability: AC-08, AC-09, FR-19, FR-20, FR-29 participation history quick actions. */
describe("deriveMyRegistrationQuickActions", () => {
  it("FR-29 / AC-08 / FR-19: shows feedback link for attended participant on completed event within window", () => {
    const actions = deriveMyRegistrationQuickActions(buildItem(), MID);
    assert.equal(actions.showFeedback, true);
    assert.equal(actions.showCheckIn, false);
  });

  it("FR-29 / AC-09 / FR-20 / AC-09e: shows eligibility link after event completion for attended registration", () => {
    const actions = deriveMyRegistrationQuickActions(buildItem(), MID);
    assert.equal(actions.showEligibility, true);
  });

  it("FR-29 / AC-09 / FR-20 / AC-09d: shows eligibility link for absent registration on completed event", () => {
    const actions = deriveMyRegistrationQuickActions(
      buildItem({ state: "Absent" }),
      MID,
    );
    assert.equal(actions.showEligibility, true);
    assert.equal(actions.showFeedback, false);
  });

  it("AC-08 / BR-15: hides feedback link when registration is not attended", () => {
    const actions = deriveMyRegistrationQuickActions(
      buildItem({ state: "Registered" }),
      MID,
    );
    assert.equal(actions.showFeedback, false);
  });

  it("AC-09f / FR-20a: hides eligibility link before attendance is finalized", () => {
    const actions = deriveMyRegistrationQuickActions(
      buildItem({ eventState: "InProgress", state: "CheckedIn" }),
      MID,
    );
    assert.equal(actions.showEligibility, false);
  });

  it("BR-14 / AC-09c: eligibility link visible while mandatory feedback is still outstanding", () => {
    const actions = deriveMyRegistrationQuickActions(buildItem(), MID);
    assert.equal(actions.showEligibility, true);
    assert.equal(actions.showFeedback, true);
  });
});
