import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  BUSINESS_RULE_IDS,
  CERTIFICATE_ELIGIBILITY_STATE_TRANSITIONS,
  CERTIFICATE_ELIGIBILITY_STATES,
  DOMAIN_EVENTS,
  EVENT_STATE_TRANSITIONS,
  EVENT_STATES,
  EXTENDED_BUSINESS_RULE_IDS,
  EXTENDED_RULE_TO_ERROR_CODE,
  REGISTRATION_STATE_TRANSITIONS,
  REGISTRATION_STATES,
  RULE_TO_ERROR_CODE,
  VALIDATION_ERROR_CODES,
  isValidCertificateEligibilityTransition,
  isValidEventTransition,
  isValidRegistrationTransition,
} from "./index.js";

describe("domain enums", () => {
  it("defines canonical event lifecycle states", () => {
    assert.deepEqual([...EVENT_STATES], [
      "Draft",
      "Published",
      "RegistrationOpen",
      "RegistrationClosed",
      "InProgress",
      "Completed",
      "Archived",
      "Cancelled",
    ]);
  });

  it("defines canonical registration lifecycle states", () => {
    assert.deepEqual([...REGISTRATION_STATES], [
      "Requested",
      "Registered",
      "Waitlisted",
      "Rejected",
      "CancelledByUser",
      "CancelledByOrganizer",
      "CheckedIn",
      "Attended",
      "Absent",
      "Expired",
    ]);
  });

  it("defines canonical certificate eligibility states", () => {
    assert.deepEqual([...CERTIFICATE_ELIGIBILITY_STATES], [
      "PendingEvaluation",
      "Eligible",
      "NotEligible",
      "Revoked",
    ]);
  });

  it("lists domain event names from the domain model", () => {
    assert.equal(DOMAIN_EVENTS.length, 12);
    assert.ok(DOMAIN_EVENTS.includes("RegistrationAccepted"));
    assert.ok(DOMAIN_EVENTS.includes("EligibilityEvaluated"));
  });
});

describe("event state machine", () => {
  it("allows documented transitions", () => {
    assert.equal(isValidEventTransition("Draft", "Published"), true);
    assert.equal(
      isValidEventTransition("Published", "RegistrationOpen"),
      true,
    );
    assert.equal(
      isValidEventTransition("RegistrationOpen", "Cancelled"),
      true,
    );
    assert.equal(EVENT_STATE_TRANSITIONS.length, 9);
  });

  it("rejects invalid transitions", () => {
    assert.equal(isValidEventTransition("Draft", "Completed"), false);
    assert.equal(isValidEventTransition("Archived", "Draft"), false);
  });
});

describe("registration state machine", () => {
  it("allows documented transitions", () => {
    assert.equal(
      isValidRegistrationTransition("Requested", "Registered"),
      true,
    );
    assert.equal(
      isValidRegistrationTransition("Registered", "CheckedIn"),
      true,
    );
    assert.equal(
      isValidRegistrationTransition("Waitlisted", "Expired"),
      true,
    );
    assert.equal(REGISTRATION_STATE_TRANSITIONS.length, 10);
  });

  it("rejects invalid transitions", () => {
    assert.equal(
      isValidRegistrationTransition("Rejected", "Registered"),
      false,
    );
    assert.equal(
      isValidRegistrationTransition("Attended", "CheckedIn"),
      false,
    );
  });
});

describe("certificate eligibility state machine", () => {
  it("allows documented transitions", () => {
    assert.equal(
      isValidCertificateEligibilityTransition(
        "PendingEvaluation",
        "Eligible",
      ),
      true,
    );
    assert.equal(
      isValidCertificateEligibilityTransition("Eligible", "Revoked"),
      true,
    );
    assert.equal(CERTIFICATE_ELIGIBILITY_STATE_TRANSITIONS.length, 3);
  });

  it("rejects invalid transitions", () => {
    assert.equal(
      isValidCertificateEligibilityTransition("NotEligible", "Eligible"),
      false,
    );
  });
});

describe("validation rule identifiers", () => {
  it("BR-01 maps to REGISTRATION_DUPLICATE_ACTIVE", () => {
    assert.equal(BUSINESS_RULE_IDS.BR_01, "BR-01");
    assert.equal(
      RULE_TO_ERROR_CODE["BR-01"],
      VALIDATION_ERROR_CODES.REGISTRATION_DUPLICATE_ACTIVE,
    );
  });

  it("BR-03 maps to CAPACITY_EXCEEDED", () => {
    assert.equal(BUSINESS_RULE_IDS.BR_03, "BR-03");
    assert.equal(
      RULE_TO_ERROR_CODE["BR-03"],
      VALIDATION_ERROR_CODES.CAPACITY_EXCEEDED,
    );
  });

  it("BR-10 maps to CHECKIN_WINDOW_CLOSED", () => {
    assert.equal(BUSINESS_RULE_IDS.BR_10, "BR-10");
    assert.equal(
      RULE_TO_ERROR_CODE["BR-10"],
      VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED,
    );
  });

  it("BR-04 is a routing rule without a public error code", () => {
    assert.equal(BUSINESS_RULE_IDS.BR_04, "BR-04");
    assert.equal(RULE_TO_ERROR_CODE["BR-04"], null);
  });

  it("BR-12 is an invariant rule without a public error code", () => {
    assert.equal(BUSINESS_RULE_IDS.BR_12, "BR-12");
    assert.equal(RULE_TO_ERROR_CODE["BR-12"], null);
  });

  it("BR-06b maps concurrent promotion guard to WAITLIST_ORDER_CONFLICT", () => {
    assert.equal(EXTENDED_BUSINESS_RULE_IDS.BR_06B, "BR-06b");
    assert.equal(
      EXTENDED_RULE_TO_ERROR_CODE["BR-06b"],
      VALIDATION_ERROR_CODES.WAITLIST_ORDER_CONFLICT,
    );
  });

  it("BR-08b is an atomic seat-release invariant without a public error code", () => {
    assert.equal(EXTENDED_BUSINESS_RULE_IDS.BR_08B, "BR-08b");
    assert.equal(EXTENDED_RULE_TO_ERROR_CODE["BR-08b"], null);
  });

  it("covers BR-04a/b, BR-06a/b, and BR-08a/b extended sub-rule identifiers", () => {
    const extendedIds = Object.values(EXTENDED_BUSINESS_RULE_IDS);
    assert.equal(extendedIds.length, 6);
    for (const ruleId of extendedIds) {
      assert.ok(ruleId in EXTENDED_RULE_TO_ERROR_CODE);
    }
  });

  it("covers BR-01 through BR-22 with stable error codes where defined", () => {
    const ruleIds = Object.values(BUSINESS_RULE_IDS);
    assert.equal(ruleIds.length, 22);
    for (const ruleId of ruleIds) {
      assert.ok(ruleId in RULE_TO_ERROR_CODE);
    }
  });
});
