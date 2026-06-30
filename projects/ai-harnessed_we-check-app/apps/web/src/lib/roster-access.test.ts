import { UserRole } from "@wecheck/domain";
import { describe, expect, it } from "vitest";
import { canImportRoster, canViewRoster } from "@/lib/roster-access";

/** FR-03 / AC-03 — roster page RBAC helpers */
describe("roster-access (AC-03, FR-03)", () => {
  it("TC-AC-03-018: instructor can view roster listing", () => {
    expect(canViewRoster(UserRole.Instructor)).toBe(true);
    expect(canImportRoster(UserRole.Instructor)).toBe(false);
  });

  it("TC-AC-03-008: only admin can import roster CSV", () => {
    expect(canViewRoster(UserRole.TrainingOfficeAdmin)).toBe(true);
    expect(canImportRoster(UserRole.TrainingOfficeAdmin)).toBe(true);
    expect(canViewRoster(UserRole.Student)).toBe(false);
    expect(canImportRoster(UserRole.Student)).toBe(false);
  });
});
