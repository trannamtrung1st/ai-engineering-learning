import { describe, expect, it } from "vitest";
import {
  canAccessInstitutionReport,
  canExecuteExport,
  isAcademicAdmin,
  isStudentOnly,
} from "./role-guard.js";

/** Traceability: BR-19 AC-16 FR-37 */
describe("role-guard — BR-19 AC-16", () => {
  it("denies institution report UI for student-only roles", () => {
    expect(canAccessInstitutionReport(["Student"])).toBe(false);
    expect(isStudentOnly(["Student"])).toBe(true);
  });

  it("allows lecturer institution report access", () => {
    expect(canAccessInstitutionReport(["Lecturer"])).toBe(true);
  });

  it("denies export for student role", () => {
    expect(canExecuteExport(["Student"])).toBe(false);
  });

  it("allows export for scoped staff roles", () => {
    expect(canExecuteExport(["Lecturer"])).toBe(true);
    expect(canExecuteExport(["AcademicAdmin"])).toBe(true);
  });

  it("identifies AcademicAdmin role for admin setup pages", () => {
    expect(isAcademicAdmin(["AcademicAdmin"])).toBe(true);
    expect(isAcademicAdmin(["Lecturer"])).toBe(false);
  });
});
