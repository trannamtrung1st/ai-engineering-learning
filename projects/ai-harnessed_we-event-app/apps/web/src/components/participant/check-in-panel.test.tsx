import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import type { EventSummary, RegistrationStatus } from "@/lib/participant-api";

import {
  CheckInPanelView,
  deriveCheckInPanelState,
} from "./check-in-panel-view.js";

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
    state: "InProgress",
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
      feedbackOpenAt: "2025-06-01T17:00:00.000Z",
      feedbackCloseAt: "2025-06-02T00:00:00.000Z",
      registrationPaused: false,
      selfCheckinEnabled: true,
      version: 1,
    },
    ...overrides,
  };
}

const registration: RegistrationStatus = {
  registrationId: "reg-1",
  eventId: "evt-1",
  participantId: "part-1",
  state: "Registered",
  reasonCode: null,
  reasonText: null,
  waitlistPosition: null,
  requestedAt: "2025-05-15T10:00:00.000Z",
  updatedAt: "2025-05-15T10:05:00.000Z",
  version: 1,
};

describe("deriveCheckInPanelState", () => {
  it("AC-05 / FR-14 / FR-15: allows check-in when registered, in progress, and inside window", () => {
    const state = deriveCheckInPanelState(buildEvent(), registration, MID);
    assert.equal(state.showCheckInButton, true);
    assert.equal(state.blockReason, null);
  });

  it("AC-06 / FR-15: blocks check-in outside the configured window", () => {
    const beforeOpen = new Date("2019-12-31T23:59:00.000Z").getTime();
    const state = deriveCheckInPanelState(buildEvent(), registration, beforeOpen);
    assert.equal(state.showCheckInButton, false);
    assert.equal(state.blockReason, "outside-window");
  });

  it("FR-14: blocks check-in at exclusive close boundary", () => {
    const atClose = new Date(CLOSE).getTime();
    const state = deriveCheckInPanelState(buildEvent(), registration, atClose);
    assert.equal(state.showCheckInButton, false);
    assert.equal(state.blockReason, "outside-window");
  });

  it("FR-14: blocks check-in when self-service is disabled", () => {
    const event = buildEvent({
      ruleConfig: {
        ...buildEvent().ruleConfig,
        selfCheckinEnabled: false,
      },
    });
    const state = deriveCheckInPanelState(event, registration, MID);
    assert.equal(state.showCheckInButton, false);
    assert.equal(state.blockReason, "self-checkin-disabled");
  });

  it("AC-05 / FR-16: treats CheckedIn and Attended as already checked in", () => {
    for (const regState of ["CheckedIn", "Attended"] as const) {
      const checkedIn = { ...registration, state: regState };
      const state = deriveCheckInPanelState(buildEvent(), checkedIn, MID);
      assert.equal(state.alreadyCheckedIn, true);
      assert.equal(state.showCheckInButton, false);
      assert.equal(state.blockReason, "already-checked-in");
    }
  });

  it("blocks check-in when participant has no registration", () => {
    const state = deriveCheckInPanelState(buildEvent(), null, MID);
    assert.equal(state.blockReason, "no-registration");
    assert.equal(state.showCheckInButton, false);
  });

  it("blocks check-in for waitlisted participant", () => {
    const waitlisted = { ...registration, state: "Waitlisted" as const, waitlistPosition: 1 };
    const state = deriveCheckInPanelState(buildEvent(), waitlisted, MID);
    assert.equal(state.blockReason, "not-registered-state");
  });
});

describe("CheckInPanelView", () => {
  it("AC-05 / FR-14: renders check-in button and window when eligible", () => {
    const panelState = deriveCheckInPanelState(buildEvent(), registration, MID);
    const html = renderToStaticMarkup(
      <CheckInPanelView event={buildEvent()} registration={registration} panelState={panelState} />,
    );
    assert.match(html, /Check in now/);
    assert.match(html, /Check-in window/);
    assert.match(html, /Registered/);
  });

  it("AC-05 / FR-16: shows success timestamp after check-in", () => {
    const panelState = deriveCheckInPanelState(buildEvent(), registration, MID);
    const html = renderToStaticMarkup(
      <CheckInPanelView
        event={buildEvent()}
        registration={registration}
        panelState={panelState}
        submitSuccess
        successTimestamp="2025-06-01T12:30:00.000Z"
      />,
    );
    assert.match(html, /You are checked in/);
    assert.match(html, /Checked in at/);
    assert.doesNotMatch(html, /Check in now/);
  });

  it("AC-06 / FR-15: shows outside-window blocking reason", () => {
    const panelState = deriveCheckInPanelState(
      buildEvent(),
      registration,
      new Date("2019-12-31T23:59:00.000Z").getTime(),
    );
    const html = renderToStaticMarkup(
      <CheckInPanelView event={buildEvent()} registration={registration} panelState={panelState} />,
    );
    assert.match(html, /Outside check-in window/);
    assert.match(html, /not available at this time/i);
    assert.doesNotMatch(html, /Check in now/);
  });

  it("FR-14: shows self-service disabled message", () => {
    const event = buildEvent({
      ruleConfig: { ...buildEvent().ruleConfig, selfCheckinEnabled: false },
    });
    const panelState = deriveCheckInPanelState(event, registration, MID);
    const html = renderToStaticMarkup(
      <CheckInPanelView event={event} registration={registration} panelState={panelState} />,
    );
    assert.match(html, /Self check-in unavailable/);
    assert.match(html, /not enabled for this event/i);
    assert.doesNotMatch(html, /Check in now/);
  });

  it("shows not-registered blocking reason for waitlisted participant", () => {
    const waitlisted = { ...registration, state: "Waitlisted" as const, waitlistPosition: 2 };
    const panelState = deriveCheckInPanelState(buildEvent(), waitlisted, MID);
    const html = renderToStaticMarkup(
      <CheckInPanelView event={buildEvent()} registration={waitlisted} panelState={panelState} />,
    );
    assert.match(html, /No active registration|Check-in not available/);
    assert.match(html, /Waitlisted|does not allow self check-in/i);
    assert.doesNotMatch(html, /Check in now/);
  });

  it("AC-07 / FR-16: shows already-checked-in copy for Attended state", () => {
    const attended = { ...registration, state: "Attended" as const };
    const panelState = deriveCheckInPanelState(buildEvent(), attended, MID);
    const html = renderToStaticMarkup(
      <CheckInPanelView event={buildEvent()} registration={attended} panelState={panelState} />,
    );
    assert.match(html, /already checked in/i);
    assert.match(html, /Attended/);
    assert.doesNotMatch(html, /Check in now/);
  });

  it("shows API duplicate check-in error inline", () => {
    const panelState = deriveCheckInPanelState(buildEvent(), registration, MID);
    const html = renderToStaticMarkup(
      <CheckInPanelView
        event={buildEvent()}
        registration={registration}
        panelState={panelState}
        submitError="A check-in has already been recorded for this registration."
      />,
    );
    assert.match(html, /Check-in blocked/);
    assert.match(html, /already been recorded/i);
  });
});
