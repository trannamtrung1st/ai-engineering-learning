import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { VALIDATION_ERROR_CODES } from "@we-event/domain";
import { ApiError } from "../../errors/api-error.js";
import type { EventWithConfig } from "../event/types.js";
import type { RegistrationRow } from "../registration/types.js";
import type { FeedbackRow } from "../feedback/types.js";
import type { EligibilityRow } from "./types.js";
import {
  ELIGIBLE_REASON_CODE,
  assertRevokeAllowed,
  evaluateEligibilityRules,
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

function buildFeedback(): FeedbackRow {
  const now = new Date().toISOString();
  return {
    id: "00000000-0000-0000-0000-000000000040",
    eventId: "00000000-0000-0000-0000-000000000010",
    registrationId: "00000000-0000-0000-0000-000000000020",
    participantId: "00000000-0000-0000-0000-000000000030",
    submittedAt: now,
    payload: { q1: 5 },
    createdAt: now,
    updatedAt: now,
  };
}

function buildEligibility(
  overrides: Partial<EligibilityRow> = {},
): EligibilityRow {
  const now = new Date().toISOString();
  return {
    id: "00000000-0000-0000-0000-000000000050",
    eventId: "00000000-0000-0000-0000-000000000010",
    registrationId: "00000000-0000-0000-0000-000000000020",
    participantId: "00000000-0000-0000-0000-000000000030",
    result: "Eligible",
    reasonCode: ELIGIBLE_REASON_CODE,
    reasonText: "Eligible",
    evaluatedAt: now,
    overriddenBy: null,
    createdAt: now,
    updatedAt: now,
    version: 1,
    ...overrides,
  };
}

describe("eligibility validation", () => {
  it("returns NotEligible when participant did not attend", () => {
    const result = evaluateEligibilityRules(
      buildRegistration({ state: "Absent" }),
      buildEvent(),
      null,
    );

    assert.equal(result.result, "NotEligible");
    assert.equal(
      result.reasonCode,
      VALIDATION_ERROR_CODES.NOT_ELIGIBLE_ATTENDANCE,
    );
  });

  it("returns NotEligible when mandatory feedback is missing", () => {
    const result = evaluateEligibilityRules(
      buildRegistration(),
      buildEvent(),
      null,
    );

    assert.equal(result.result, "NotEligible");
    assert.equal(
      result.reasonCode,
      VALIDATION_ERROR_CODES.NOT_ELIGIBLE_FEEDBACK,
    );
  });

  it("returns Eligible when attendance and feedback requirements pass", () => {
    const result = evaluateEligibilityRules(
      buildRegistration(),
      buildEvent(),
      buildFeedback(),
    );

    assert.equal(result.result, "Eligible");
    assert.equal(result.reasonCode, ELIGIBLE_REASON_CODE);
    assert.ok(result.reasonText.length > 0);
  });

  it("rejects revoke without admin role and reason", () => {
    assert.throws(
      () =>
        assertRevokeAllowed(
          buildEligibility(),
          "OrganizerStaff",
          "ADMIN_REVOKED",
          "Policy violation",
        ),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(
          error.code,
          VALIDATION_ERROR_CODES.ELIGIBILITY_OVERRIDE_FORBIDDEN,
        );
        return true;
      },
    );
  });
});
