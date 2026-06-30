import { UserRole } from "@wecheck/domain";
import { describe, expect, it } from "vitest";
import {
  canAccessAdminShell,
  getAdminForbiddenDescription,
  isInstructorRosterPath,
} from "@/lib/admin-route-access";
import { reportCopy } from "@/lib/copy/report-labels";

/** FR-03 / AC-03c — admin shell route guards */
describe("admin-route-access (AC-03, FR-03)", () => {
  it("TC-AC-03-018: instructor roster paths are allowed", () => {
    expect(isInstructorRosterPath("/admin/rosters")).toBe(true);
    expect(isInstructorRosterPath("/admin/rosters/HESD-01")).toBe(true);
    expect(isInstructorRosterPath("/admin/rosters/import")).toBe(false);
    expect(isInstructorRosterPath("/admin/classes/new")).toBe(false);
    expect(
      canAccessAdminShell(UserRole.Instructor, "/admin/rosters"),
    ).toBe(true);
    expect(
      canAccessAdminShell(UserRole.Instructor, "/admin/export"),
    ).toBe(false);
  });

  it("TC-NFR-11-017: student denied all admin shell routes", () => {
    expect(canAccessAdminShell(UserRole.Student, "/admin/rosters")).toBe(false);
    expect(canAccessAdminShell(UserRole.Student, "/admin/export")).toBe(false);
  });

  it("TC-NFR-17-019 / AC-13b: export path returns Vietnamese export-denied copy", () => {
    expect(getAdminForbiddenDescription("/admin/export")).toBe(
      reportCopy.exportDenied,
    );
    expect(getAdminForbiddenDescription("/admin/users")).toBeUndefined();
  });
});
