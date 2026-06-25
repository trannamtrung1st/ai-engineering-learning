import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";
import { ApiError } from "../../errors/api-error.js";
import type { EventWithConfig } from "../event/types.js";
import type { RegistrationRow } from "../registration/types.js";
import type { CheckinRecordRow } from "./types.js";
import {
  assertCheckinWindowOpen,
  assertNoExistingCheckin,
  assertRegistrationCheckinable,
  assertSelfCheckinAllowed,
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
    state: "InProgress",
    startAt: open,
    endAt: close,
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

function buildCheckin(
  overrides: Partial<CheckinRecordRow> = {},
): CheckinRecordRow {
  const now = new Date().toISOString();
  return {
    id: "00000000-0000-0000-0000-000000000040",
    registrationId: "00000000-0000-0000-0000-000000000020",
    eventId: "00000000-0000-0000-0000-000000000010",
    checkinAt: now,
    method: "Staff",
    operatorId: "00000000-0000-0000-0000-000000000099",
    createdAt: now,
    ...overrides,
  };
}

describe("checkin validation", () => {
  it("assertCheckinWindowOpen rejects out-of-window check-in (AC-06)", () => {
    const now = Date.now();
    const event = buildEvent({
      ruleConfig: {
        ...buildEvent().ruleConfig,
        checkinOpenAt: new Date(now + 3_600_000).toISOString(),
        checkinCloseAt: new Date(now + 7_200_000).toISOString(),
      },
    });

    assert.throws(
      () => assertCheckinWindowOpen(event, now),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED);
        return true;
      },
    );
  });

  it("assertCheckinWindowOpen allows in-window check-in", () => {
    const event = buildEvent();
    assert.doesNotThrow(() => assertCheckinWindowOpen(event));
  });

  it("assertNoExistingCheckin rejects duplicate check-in (BR-11)", () => {
    const existing = buildCheckin();
    assert.throws(
      () => assertNoExistingCheckin(existing),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(
          error.code,
          VALIDATION_ERROR_CODES.CHECKIN_ALREADY_RECORDED,
        );
        return true;
      },
    );
  });

  it("assertRegistrationCheckinable requires Registered state", () => {
    const waitlisted = buildRegistration({ state: "Waitlisted" });
    assert.throws(
      () => assertRegistrationCheckinable(waitlisted),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, "INVALID_STATE_TRANSITION");
        return true;
      },
    );
  });

  it("assertSelfCheckinAllowed requires InProgress event", () => {
    const event = buildEvent({ state: "RegistrationOpen" });
    assert.throws(
      () => assertSelfCheckinAllowed(event),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED);
        return true;
      },
    );
  });
});
