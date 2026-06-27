import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { EventSummary, RegistrationStatus } from "@/lib/participant-api";

import { deriveFeedbackPanelState } from "./feedback-panel-view.js";

const OPEN = "2020-01-01T08:00:00.000Z";
const CLOSE = "2030-01-01T18:00:00.000Z";
const MID = new Date("2025-06-01T12:00:00.000Z").getTime();

function buildEvent(overrides: Partial<EventSummary> = {}): EventSummary {
  return {
    eventId: "evt-1",
    organizationId: "org-1",
    name: "Summit",
    description: "Regional conference",
    location: "Hall A",
    state: "Completed",
    startAt: "2025-06-01T09:00:00.000Z",
    endAt: "2025-06-01T17:00:00.000Z",
    version: 1,
    updatedAt: "2025-05-01T00:00:00.000Z",
    ruleConfig: {
      capacity: 100,
      waitlistEnabled: true,
      registrationOpenAt: "2020-01-01T00:00:00.000Z",
      registrationCloseAt: "2030-01-01T00:00:00.000Z",
      checkinOpenAt: OPEN,
      checkinCloseAt: CLOSE,
      feedbackRequired: true,
      feedbackOpenAt: OPEN,
      feedbackCloseAt: CLOSE,
      registrationPaused: false,
      version: 1,
    },
    ...overrides,
  };
}

const attendedRegistration: RegistrationStatus = {
  registrationId: "reg-1",
  eventId: "evt-1",
  participantId: "part-1",
  state: "Attended",
  reasonCode: null,
  reasonText: null,
  waitlistPosition: null,
  requestedAt: "2025-05-15T10:00:00.000Z",
  updatedAt: "2025-05-15T10:05:00.000Z",
  version: 1,
};

describe("deriveFeedbackPanelState", () => {
  it("AC-08 / FR-19 / BR-15: allows feedback for attended participant on completed event within window", () => {
    const state = deriveFeedbackPanelState(buildEvent(), attendedRegistration, MID);
    assert.equal(state.canSubmit, true);
    assert.equal(state.blockReason, null);
  });

  it("AC-08 / BR-15: blocks feedback when registration is not attended", () => {
    const state = deriveFeedbackPanelState(
      buildEvent(),
      { ...attendedRegistration, state: "Registered" },
      MID,
    );
    assert.equal(state.canSubmit, false);
    assert.equal(state.blockReason, "not-attended");
  });

  it("AC-08 / BR-15 / FR-19: blocks feedback outside the configured window", () => {
    const afterClose = new Date("2031-01-01T00:00:00.000Z").getTime();
    const state = deriveFeedbackPanelState(buildEvent(), attendedRegistration, afterClose);
    assert.equal(state.canSubmit, false);
    assert.equal(state.blockReason, "outside-window");
  });

  it("AC-08 / BR-15: blocks feedback before event completion", () => {
    const state = deriveFeedbackPanelState(
      buildEvent({ state: "InProgress" }),
      attendedRegistration,
      MID,
    );
    assert.equal(state.canSubmit, false);
    assert.equal(state.blockReason, "event-not-completed");
  });

  it("AC-08 / FR-19 / NFR-13: submit enabled only when all feedback gates pass", () => {
    assert.equal(deriveFeedbackPanelState(buildEvent(), attendedRegistration, MID).canSubmit, true);
    assert.equal(
      deriveFeedbackPanelState(buildEvent(), null, MID).canSubmit,
      false,
    );
  });
});
