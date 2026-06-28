import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { PASSWORD_POLICY } from "@wecheck/domain";

/**
 * Traceability: NFR-14 FR-01 FR-02 AC-01 AC-02 BR-06 FR-07
 */
describe("monorepo integration smoke", () => {
  it("resolves shared domain package from API workspace (NFR-14)", () => {
    assert.equal(PASSWORD_POLICY.MIN_LENGTH, 8);
    assert.equal(PASSWORD_POLICY.MAX_LENGTH, 128);
  });
});
