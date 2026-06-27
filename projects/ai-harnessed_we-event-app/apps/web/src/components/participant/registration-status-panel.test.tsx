import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import type { EventSummary, RegistrationStatus } from "@/lib/participant-api";

import {
  deriveRegistrationPanelState,
  RegistrationStatusPanelView,
} from "./registration-status-panel-view.js";
import { RegistrationStatusTimeline } from "./registration-status-timeline.js";

const event: EventSummary = {
  eventId: "evt-1",
  organizationId: "org-1",
  name: "Summit",
  description: "Regional conference series",
  location: "Hall A",
  state: "RegistrationOpen",
  startAt: "2026-07-01T09:00:00.000Z",
  endAt: "2026-07-01T17:00:00.000Z",
  version: 1,
  updatedAt: "2026-06-01T00:00:00.000Z",
  ruleConfig: {
    capacity: 100,
    waitlistEnabled: true,
    registrationOpenAt: "2020-01-01T00:00:00.000Z",
    registrationCloseAt: "2030-01-01T00:00:00.000Z",
    checkinOpenAt: "2026-07-01T08:00:00.000Z",
    checkinCloseAt: "2026-07-01T10:00:00.000Z",
    feedbackRequired: true,
    feedbackOpenAt: "2026-07-01T17:00:00.000Z",
    feedbackCloseAt: "2026-07-02T00:00:00.000Z",
    registrationPaused: false,
    selfCheckinEnabled: true,
    version: 1,
  },
};

const registration: RegistrationStatus = {
  registrationId: "reg-1",
  eventId: "evt-1",
  participantId: "part-1",
  state: "Registered",
  reasonCode: null,
  reasonText: null,
  waitlistPosition: null,
  requestedAt: "2026-06-15T10:00:00.000Z",
  updatedAt: "2026-06-15T10:05:00.000Z",
  version: 1,
};

const noop = () => {};

describe("RegistrationStatusPanelView", () => {
  it("AC-01 / FR-10: shows Register action when participant has no registration", () => {
    const panelState = deriveRegistrationPanelState(event, null);
    const html = renderToStaticMarkup(
      <RegistrationStatusPanelView
        registration={null}
        {...panelState}
        cancelDialogOpen={false}
        onCancelDialogOpenChange={noop}
        onRegister={noop}
        onConfirmCancel={noop}
      />,
    );
    assert.match(html, /Register/);
    assert.match(html, /not registered/i);
    assert.doesNotMatch(html, /Cancel registration/);
  });

  it("AC-02 / FR-10: shows waitlisted status with queue position and promotion copy", () => {
    const waitlisted = { ...registration, state: "Waitlisted" as const, waitlistPosition: 2 };
    const panelState = deriveRegistrationPanelState(event, waitlisted);
    const html = renderToStaticMarkup(
      <RegistrationStatusPanelView
        registration={waitlisted}
        {...panelState}
        cancelDialogOpen={false}
        onCancelDialogOpenChange={noop}
        onRegister={noop}
        onConfirmCancel={noop}
      />,
    );
    assert.match(html, /Waitlisted/);
    assert.match(html, /Queue position: 2/);
    assert.match(html, /automatically when a seat opens/i);
    assert.match(html, /Cancel registration/);
  });

  it("AC-03 / FR-11: hides Register when participant already registered", () => {
    const panelState = deriveRegistrationPanelState(event, registration);
    const html = renderToStaticMarkup(
      <RegistrationStatusPanelView
        registration={registration}
        {...panelState}
        cancelDialogOpen={false}
        onCancelDialogOpenChange={noop}
        onRegister={noop}
        onConfirmCancel={noop}
      />,
    );
    assert.match(html, /Registered/);
    assert.match(html, /Cancel registration/);
    assert.doesNotMatch(html, />Register</);
  });

  it("FR-11: shows rejection reason when registration rejected", () => {
    const rejected = {
      ...registration,
      state: "Rejected" as const,
      reasonText: "Registration window closed before review.",
    };
    const panelState = deriveRegistrationPanelState(event, rejected);
    const html = renderToStaticMarkup(
      <RegistrationStatusPanelView
        registration={rejected}
        {...panelState}
        cancelDialogOpen={false}
        onCancelDialogOpenChange={noop}
        onRegister={noop}
        onConfirmCancel={noop}
      />,
    );
    assert.match(html, /Rejected/);
    assert.match(html, /Registration window closed before review/);
    assert.doesNotMatch(html, /Cancel registration/);
  });
});

describe("RegistrationStatusTimeline", () => {
  it("FR-29: renders status badge, timeline timestamps, and waitlist position", () => {
    const html = renderToStaticMarkup(
      <RegistrationStatusTimeline
        state="Waitlisted"
        updatedAt="2026-06-15T10:05:00.000Z"
        waitlistPosition={1}
        reasonText={null}
      />,
    );
    assert.match(html, /Waitlisted/);
    assert.match(html, /Queue position: 1/);
    assert.match(html, /Last updated/);
    assert.match(html, /Current status/);
  });
});
