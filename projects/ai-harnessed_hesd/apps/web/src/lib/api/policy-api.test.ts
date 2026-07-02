/**
 * Traceability: FR-24 FR-25 BR-20
 * TC-FR-24-004 TC-FR-25-002
 */
import { describe, expect, it } from "vitest";
import {
  buildDefaultScopeNameLookup,
  resolvePolicyScopeName,
  type PolicySummary,
} from "./policy-api";

describe("policy-api (FR-24)", () => {
  it("TC-FR-24-004: resolvePolicyScopeName maps institution scope", () => {
    const lookup = buildDefaultScopeNameLookup();
    const name = resolvePolicyScopeName(
      { scopeType: "Institution", scopeId: null },
      lookup,
    );
    expect(name).toBe("Toàn trường");
  });

  it("TC-FR-25-002: resolvePolicyScopeName maps class section seed label", () => {
    const lookup = buildDefaultScopeNameLookup();
    const policy: Pick<PolicySummary, "scopeType" | "scopeId"> = {
      scopeType: "ClassSection",
      scopeId: "50000000-0000-4000-8000-000000000001",
    };
    expect(resolvePolicyScopeName(policy, lookup)).toBe("SE101-01");
  });
});
