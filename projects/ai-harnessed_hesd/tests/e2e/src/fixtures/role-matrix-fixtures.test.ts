import { describe, expect, it } from "vitest";
import { ROLE_MATRIX_EMAILS, ROLE_MATRIX_SEED } from "./role-matrix-fixtures.js";

describe("role-matrix fixtures — deterministic IDs", () => {
  it("REG-04 exposes stable hierarchy IDs for AC-15 AC-16 AC-17 traceability", () => {
    expect(ROLE_MATRIX_SEED.sectionA).toMatch(
      /^50000000-0000-4000-8000-0000000000/,
    );
    expect(ROLE_MATRIX_SEED.sectionB).not.toBe(ROLE_MATRIX_SEED.sectionA);
    expect(ROLE_MATRIX_EMAILS.lecturer).toBe("lecturer@attendly.local");
    expect(ROLE_MATRIX_EMAILS.itAdmin).toContain("e2e-itadmin");
  });
});
