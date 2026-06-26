import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  canCancelRegistration,
  canRegister,
  canSelfCheckIn,
  canSubmitFeedback,
  canViewEligibility,
  isWithinTimeWindow,
} from "./participant-rules.js";

const OPEN = "2026-06-01T09:00:00.000Z";
const CLOSE = "2026-06-01T17:00:00.000Z";
const MID = new Date("2026-06-01T12:00:00.000Z").getTime();

/** Traceability: AC-01, AC-05, AC-08, FR-10, FR-28, FR-29 and related BR/NFR tags. */
describe("participant UX gating rules", () => {
  describe("AC-01 / FR-10 / BR-02 registration", () => {
    it("allows register when event is open, window active, and no active registration", () => {
      assert.equal(
        canRegister("RegistrationOpen", false, OPEN, CLOSE, null, MID),
        true,
      );
    });

    it("blocks register when participant already has active registration", () => {
      assert.equal(
        canRegister("RegistrationOpen", false, OPEN, CLOSE, "Registered", MID),
        false,
      );
    });

    it("blocks register when registration is paused", () => {
      assert.equal(
        canRegister("RegistrationOpen", true, OPEN, CLOSE, null, MID),
        false,
      );
    });
  });

  describe("AC-05 / FR-13 / FR-14 / FR-15 / FR-16 self check-in", () => {
    it("allows check-in for registered participant during in-progress event and window", () => {
      assert.equal(
        canSelfCheckIn("InProgress", "Registered", OPEN, CLOSE, MID),
        true,
      );
    });

    it("blocks check-in outside the configured window", () => {
      const beforeOpen = new Date("2026-06-01T08:00:00.000Z").getTime();
      assert.equal(
        canSelfCheckIn("InProgress", "Registered", OPEN, CLOSE, beforeOpen),
        false,
      );
    });
  });

  describe("AC-08 / FR-19 / BR-15 / BR-16 feedback", () => {
    it("allows feedback for attended participant after event completion within window", () => {
      assert.equal(
        canSubmitFeedback("Completed", "Attended", OPEN, CLOSE, MID),
        true,
      );
    });

    it("blocks feedback when registration is not attended", () => {
      assert.equal(
        canSubmitFeedback("Completed", "Registered", OPEN, CLOSE, MID),
        false,
      );
    });
  });

  describe("FR-28 / FR-29 / FR-31 / NFR-12 supporting rules", () => {
    it("isWithinTimeWindow returns true only inside open/close bounds", () => {
      assert.equal(isWithinTimeWindow(OPEN, CLOSE, MID), true);
      assert.equal(
        isWithinTimeWindow(OPEN, CLOSE, new Date("2026-06-02T00:00:00.000Z").getTime()),
        false,
      );
    });

    it("canCancelRegistration allows registered users before registration close", () => {
      assert.equal(canCancelRegistration("Registered", CLOSE, MID), true);
      assert.equal(
        canCancelRegistration("Registered", CLOSE, new Date("2026-06-02T00:00:00.000Z").getTime()),
        false,
      );
    });

    it("canViewEligibility requires completed event and attended/absent registration", () => {
      assert.equal(canViewEligibility("Completed", "Attended"), true);
      assert.equal(canViewEligibility("Completed", "Registered"), false);
      assert.equal(canViewEligibility("Completed", "CheckedIn"), false);
    });
  });

  describe("FR-29 my registrations quick actions", () => {
    it("check-in link only when event is in progress and window is open", () => {
      assert.equal(
        canSelfCheckIn("InProgress", "Registered", OPEN, CLOSE, MID),
        true,
      );
      assert.equal(
        canSelfCheckIn("RegistrationOpen", "Registered", OPEN, CLOSE, MID),
        false,
      );
      assert.equal(
        canSelfCheckIn("InProgress", "Attended", OPEN, CLOSE, MID),
        false,
      );
    });

    it("feedback link only for attended participants on completed events within window", () => {
      assert.equal(
        canSubmitFeedback("Completed", "Attended", OPEN, CLOSE, MID),
        true,
      );
      assert.equal(
        canSubmitFeedback("InProgress", "Attended", OPEN, CLOSE, MID),
        false,
      );
      assert.equal(
        canSubmitFeedback("Completed", "Registered", OPEN, CLOSE, MID),
        false,
      );
    });

    it("eligibility link only after event completion for attended or absent", () => {
      assert.equal(canViewEligibility("Completed", "Absent"), true);
      assert.equal(canViewEligibility("InProgress", "Attended"), false);
    });
  });
});
