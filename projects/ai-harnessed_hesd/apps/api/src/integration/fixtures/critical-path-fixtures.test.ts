/**
 * Traceability: AC-01 AC-04 AC-08 AC-12 AC-18 NFR-07
 */
import { describe, expect, it } from "vitest";
import { CRITICAL_PATH_SEED } from "./critical-path-fixtures.js";

describe("critical-path fixtures — deterministic IDs", () => {
  it("TC-AC-01-002: isolated hierarchy IDs remain stable for REG suite", () => {
    expect(CRITICAL_PATH_SEED.sectionA).toMatch(
      /^50000000-0000-4000-8000-00000000008[89]$/,
    );
    expect(CRITICAL_PATH_SEED.faculty).not.toBe("10000000-0000-4000-8000-000000000001");
    expect(CRITICAL_PATH_SEED.course).not.toBe("30000000-0000-4000-8000-000000000001");
  });
});
