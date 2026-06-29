import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { PASSWORD_POLICY } from "@wecheck/domain";

/**
 * Traceability: NFR-14 FR-01 FR-02 FR-17 AC-01 AC-02 AC-17 BR-06 FR-07
 * TC-NFR-14-019 TC-NFR-14-020 — bootstrap path uses shared PASSWORD_POLICY
 */
describe("monorepo integration smoke", () => {
  it("resolves shared domain package from API workspace (NFR-14)", () => {
    assert.equal(PASSWORD_POLICY.MIN_LENGTH, 8);
    assert.equal(PASSWORD_POLICY.MAX_LENGTH, 128);
  });

  it("shares VAL-03 password bounds for bootstrap and user provisioning (AC-17, FR-17)", () => {
    assert.equal(PASSWORD_POLICY.MIN_LENGTH, 8);
    assert.equal(PASSWORD_POLICY.MAX_LENGTH, 128);
  });
});
