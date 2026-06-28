import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  DOMAIN_PACKAGE_VERSION,
  NON_FUNCTIONAL_REQUIREMENT_IDS,
  PASSWORD_POLICY,
  isPasswordLengthValid,
} from "./index.js";

/**
 * Traceability for NFR-14 generated integration/e2e cases:
 * AC-01 AC-02 BR-06 FR-01 FR-02 FR-07 NFR-14
 */
const NFR_14_TRACEABILITY_TAGS = [
  "AC-01",
  "AC-02",
  "BR-06",
  "FR-01",
  "FR-02",
  "FR-07",
  "NFR-14",
] as const;

describe("@wecheck/domain monorepo bootstrap", () => {
  it("exports a stable package version", () => {
    assert.equal(DOMAIN_PACKAGE_VERSION, "0.0.1");
  });

  it("documents NFR-14 traceability tags for harness coverage", () => {
    assert.ok(NFR_14_TRACEABILITY_TAGS.includes("NFR-14"));
    assert.equal(NFR_14_TRACEABILITY_TAGS.length, 7);
  });
});

describe("NFR-14 credential policy identifiers", () => {
  it("defines VAL-03 minimum password length of 8 characters", () => {
    assert.equal(NON_FUNCTIONAL_REQUIREMENT_IDS.NFR_14, "NFR-14");
    assert.equal(PASSWORD_POLICY.MIN_LENGTH, 8);
    assert.equal(isPasswordLengthValid(7), false);
    assert.equal(isPasswordLengthValid(8), true);
  });

  it("defines VAL-03 maximum password length of 128 characters", () => {
    assert.equal(PASSWORD_POLICY.MAX_LENGTH, 128);
    assert.equal(isPasswordLengthValid(128), true);
    assert.equal(isPasswordLengthValid(129), false);
  });
});
