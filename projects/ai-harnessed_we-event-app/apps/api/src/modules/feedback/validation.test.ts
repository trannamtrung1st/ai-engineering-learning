import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";
import { ApiError } from "../../errors/api-error.js";
import type { EventWithConfig } from "../event/types.js";
import type { RegistrationRow } from "../registration/types.js";
import {
  assertAnswersValid,
  assertFeedbackWindowOpen,
  assertNoDuplicateOutsideWindow,
  assertRegistrationFeedbackEligible,
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
    state: "Completed",
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
      feedbackRequired: true,
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
    state: "Attended",
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

describe("feedback validation", () => {
  it("rejects feedback outside the configured window (FR-19, BR-15)", () => {
    const event = buildEvent({
      ruleConfig: {
        ...buildEvent().ruleConfig,
        feedbackOpenAt: new Date(Date.now() + 86_400_000).toISOString(),
        feedbackCloseAt: new Date(Date.now() + 172_800_000).toISOString(),
      },
    });

    assert.throws(
      () => assertFeedbackWindowOpen(event),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, VALIDATION_ERROR_CODES.FEEDBACK_NOT_ALLOWED);
        return true;
      },
    );
  });

  it("rejects feedback from non-attended registrations (BR-15)", () => {
    assert.throws(
      () =>
        assertRegistrationFeedbackEligible(
          buildRegistration({ state: "Registered" }),
        ),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, VALIDATION_ERROR_CODES.FEEDBACK_NOT_ALLOWED);
        return true;
      },
    );
  });

  it("requires non-empty answers object", () => {
    assert.throws(
      () => assertAnswersValid({}),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, "INVALID_INPUT");
        return true;
      },
    );
  });

  it("assertNoDuplicateOutsideWindow rejects resubmit when updates are not allowed (BR-16)", () => {
    const now = new Date().toISOString();
    assert.throws(
      () =>
        assertNoDuplicateOutsideWindow(
          {
            id: "00000000-0000-0000-0000-000000000050",
            eventId: "00000000-0000-0000-0000-000000000010",
            registrationId: "00000000-0000-0000-0000-000000000020",
            participantId: "00000000-0000-0000-0000-000000000030",
            payload: { q1: 4 },
            submittedAt: now,
            createdAt: now,
            updatedAt: now,
          },
          false,
        ),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, VALIDATION_ERROR_CODES.FEEDBACK_DUPLICATE);
        return true;
      },
    );
  });
});
