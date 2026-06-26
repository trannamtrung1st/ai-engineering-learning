import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";
import { ApiError } from "../../errors/api-error.js";
import type { EventWithConfig } from "../event/types.js";
import type { RegistrationRow } from "./types.js";
import {
  assertNoDuplicateActive,
  assertRegistrationWindowOpen,
  isActiveRegistrationState,
} from "./validation.js";

function buildEvent(overrides: Partial<EventWithConfig> = {}): EventWithConfig {
  const now = Date.now();
  const open = new Date(now - 3_600_000).toISOString();
  const close = new Date(now + 3_600_000).toISOString();

  return {
    id: "00000000-0000-0000-0000-000000000010",
    organizationId: "00000000-0000-0000-0000-000000000001",
    name: "Test",
    description: "",
    location: "",
    state: "RegistrationOpen",
    startAt: open,
    endAt: close,
    coverImageKey: null,
    coverImageUpdatedAt: null,
    createdBy: "00000000-0000-0000-0000-000000000099",
    updatedBy: "00000000-0000-0000-0000-000000000099",
    createdAt: open,
    updatedAt: open,
    version: 1,
    ruleConfig: {
      eventId: "00000000-0000-0000-0000-000000000010",
      capacity: 10,
      waitlistEnabled: true,
      registrationOpenAt: open,
      registrationCloseAt: close,
      checkinOpenAt: open,
      checkinCloseAt: close,
      feedbackRequired: false,
      feedbackOpenAt: open,
      feedbackCloseAt: close,
      registrationPaused: false,
      selfCheckinEnabled: true,
      version: 1,
    },
    ...overrides,
  };
}

function buildRegistration(
  overrides: Partial<RegistrationRow> = {},
): RegistrationRow {
  const now = new Date().toISOString();
  return {
    id: "00000000-0000-0000-0000-000000000020",
    eventId: "00000000-0000-0000-0000-000000000010",
    participantId: "00000000-0000-0000-0000-000000000030",
    state: "Registered",
    requestedAt: now,
    cancelledAt: null,
    statusReasonCode: null,
    statusReasonText: null,
    createdAt: now,
    updatedAt: now,
    version: 1,
    ...overrides,
  };
}

describe("registration validation", () => {
  it("isActiveRegistrationState recognizes active states", () => {
    assert.equal(isActiveRegistrationState("Registered"), true);
    assert.equal(isActiveRegistrationState("CancelledByUser"), false);
  });

  it("assertRegistrationWindowOpen rejects non-open event states (BR-02)", () => {
    const event = buildEvent({ state: "Draft" });
    assert.throws(
      () => assertRegistrationWindowOpen(event),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(
          error.code,
          VALIDATION_ERROR_CODES.REGISTRATION_WINDOW_CLOSED,
        );
        return true;
      },
    );
  });

  it("BR-01 / AC-03: assertNoDuplicateActive rejects existing active registration", () => {
    const existing = buildRegistration({ state: "Registered" });
    assert.throws(
      () => assertNoDuplicateActive(existing),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(
          error.code,
          VALIDATION_ERROR_CODES.REGISTRATION_DUPLICATE_ACTIVE,
        );
        return true;
      },
    );
  });

  it("assertNoDuplicateActive allows no existing registration", () => {
    assert.doesNotThrow(() => assertNoDuplicateActive(null));
  });
});
