import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ErrorCode } from "@wecheck/domain";
import {
  parseCreateReferenceBody,
  validateReferenceCode,
  validateReferenceName,
} from "./validation.js";

/**
 * Traceability: AC-03 FR-03
 * Cases: TC-AC-03-020 TC-AC-03-022 TC-AC-03-023 TC-FR-03-023 TC-FR-03-026
 */
describe("roster reference validation (AC-03, FR-03)", () => {
  it("validateReferenceCode accepts uppercase HESD-03", () => {
    const result = validateReferenceCode("HESD-03");
    assert.equal(result.ok, true);
    if (result.ok) {
      assert.equal(result.value, "HESD-03");
    }
  });

  it("validateReferenceCode rejects lowercase hesd-99 (TC-AC-03-020)", () => {
    const result = validateReferenceCode("hesd-99");
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(result.details[0]?.code, ErrorCode.InvalidFormat);
    }
  });

  it("validateReferenceName enforces VAL-04 length", () => {
    assert.equal(validateReferenceName("HESD Cohort 03").ok, true);
    assert.equal(validateReferenceName("   ").ok, false);
  });

  it("parseCreateReferenceBody validates class create payload", () => {
    const ok = parseCreateReferenceBody({
      code: "SWE-102",
      name: "Software Engineering 102",
    });
    assert.equal(ok.ok, true);

    const bad = parseCreateReferenceBody({ code: "swe-102", name: "Bad" });
    assert.equal(bad.ok, false);
  });
});
