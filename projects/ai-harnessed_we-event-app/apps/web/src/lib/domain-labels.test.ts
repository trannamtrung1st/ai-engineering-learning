import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  EVENT_STATES,
  REGISTRATION_STATES,
  type EventState,
  type RegistrationState,
} from "@we-event/domain";

import {
  eventStateLabel,
  registrationStateLabel,
} from "./domain-labels.js";

describe("domain-labels (NFR-06)", () => {
  it("maps every event lifecycle state to a distinct semantic badgeStatus", () => {
    const statuses = new Set<string>();

    for (const state of EVENT_STATES) {
      const { label, badgeStatus } = eventStateLabel(state);
      assert.ok(label.length > 0, `${state} must have a label`);
      assert.ok(badgeStatus, `${state} must have badgeStatus`);
      statuses.add(badgeStatus!);
    }

    assert.equal(statuses.size, EVENT_STATES.length);
  });

  it("maps every registration state to a semantic badgeStatus", () => {
    for (const state of REGISTRATION_STATES) {
      const { label, badgeStatus } = registrationStateLabel(state);
      assert.ok(label.length > 0, `${state} must have a label`);
      assert.ok(badgeStatus, `${state} must have badgeStatus`);
    }
  });

  it("uses distinct muted tokens for terminal registration states (TC-NFR-06-017)", () => {
    const terminal: Record<
      Extract<RegistrationState, "CancelledByUser" | "CancelledByOrganizer" | "Expired">,
      string
    > = {
      CancelledByUser: registrationStateLabel("CancelledByUser").badgeStatus!,
      CancelledByOrganizer: registrationStateLabel("CancelledByOrganizer").badgeStatus!,
      Expired: registrationStateLabel("Expired").badgeStatus!,
    };

    assert.equal(terminal.CancelledByUser, "cancelledByUser");
    assert.equal(terminal.CancelledByOrganizer, "cancelledByOrganizer");
    assert.equal(terminal.Expired, "expired");
    assert.equal(
      new Set(Object.values(terminal)).size,
      3,
      "terminal registration states must not share the same badge token",
    );
  });

  it("eventStateLabel covers canonical lifecycle states with expected tokens", () => {
    const expected: Partial<Record<EventState, string>> = {
      Draft: "draft",
      Published: "published",
      RegistrationOpen: "registrationOpen",
      RegistrationClosed: "registrationClosed",
      InProgress: "inProgress",
      Completed: "completed",
      Archived: "archived",
      Cancelled: "cancelledEvent",
    };

    for (const [state, token] of Object.entries(expected)) {
      assert.equal(eventStateLabel(state as EventState).badgeStatus, token);
    }
  });
});
