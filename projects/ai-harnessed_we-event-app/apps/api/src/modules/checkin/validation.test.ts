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
  it("BR-10 / AC-06 / FR-15: assertCheckinWindowOpen rejects out-of-window check-in", () => {
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

  it("assertCheckinWindowOpen allows in-window check-in (FR-13, FR-14, AC-05, TC-AC-05-004)", () => {
    const event = buildEvent();
    assert.doesNotThrow(() => assertCheckinWindowOpen(event));
  });

  it("AC-05 / TC-AC-05-007: check-in at checkinOpenAt boundary is permitted", () => {
    const openAt = "2026-06-26T10:00:00.000Z";
    const closeAt = "2026-06-26T12:00:00.000Z";
    const event = buildEvent({
      ruleConfig: {
        ...buildEvent().ruleConfig,
        checkinOpenAt: openAt,
        checkinCloseAt: closeAt,
      },
    });
    const atOpen = new Date(openAt).getTime();
    assert.doesNotThrow(() => assertCheckinWindowOpen(event, atOpen));
  });

  it("AC-06 / TC-AC-06-005: assertCheckinWindowOpen rejects time before checkinOpenAt", () => {
    const openAt = "2026-06-26T10:00:00.000Z";
    const closeAt = "2026-06-26T12:00:00.000Z";
    const event = buildEvent({
      ruleConfig: {
        ...buildEvent().ruleConfig,
        checkinOpenAt: openAt,
        checkinCloseAt: closeAt,
      },
    });
    const beforeOpen = new Date(openAt).getTime() - 1;

    assert.throws(
      () => assertCheckinWindowOpen(event, beforeOpen),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED);
        return true;
      },
    );
  });

  it("AC-06 / TC-AC-06-006: assertCheckinWindowOpen rejects time after checkinCloseAt", () => {
    const openAt = "2026-06-26T10:00:00.000Z";
    const closeAt = "2026-06-26T12:00:00.000Z";
    const event = buildEvent({
      ruleConfig: {
        ...buildEvent().ruleConfig,
        checkinOpenAt: openAt,
        checkinCloseAt: closeAt,
      },
    });
    const afterClose = new Date(closeAt).getTime() + 1;

    assert.throws(
      () => assertCheckinWindowOpen(event, afterClose),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED);
        return true;
      },
    );
  });

  it("AC-06 / TC-AC-06-007: check-in at checkinCloseAt boundary is rejected", () => {
    const openAt = "2026-06-26T10:00:00.000Z";
    const closeAt = "2026-06-26T12:00:00.000Z";
    const event = buildEvent({
      ruleConfig: {
        ...buildEvent().ruleConfig,
        checkinOpenAt: openAt,
        checkinCloseAt: closeAt,
      },
    });
    const atClose = new Date(closeAt).getTime();

    assert.throws(
      () => assertCheckinWindowOpen(event, atClose),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED);
        return true;
      },
    );
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

  it("assertSelfCheckinAllowed requires InProgress event (FR-16)", () => {
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

  it("FR-14 / TC-FR-14-007: assertSelfCheckinAllowed rejects when selfCheckinEnabled is false", () => {
    const event = buildEvent({
      ruleConfig: {
        ...buildEvent().ruleConfig,
        selfCheckinEnabled: false,
      },
    });
    assert.throws(
      () => assertSelfCheckinAllowed(event),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, VALIDATION_ERROR_CODES.SELF_CHECKIN_DISABLED);
        return true;
      },
    );
  });
});
