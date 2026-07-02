import { describe, expect, it } from "vitest";
import {
  canAccessAuditLogs,
  canAccessInstitutionReport,
  canAccessSessionControl,
  canExecuteExport,
  isAcademicAdmin,
  isReadOnlyStaffRole,
  isStudentOnly,
  isSystemAuditor,
} from "./role-guard.js";

/** Traceability: BR-19 AC-16 FR-32 FR-37 */
describe("role-guard — BR-19 AC-16 FR-32", () => {
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

  it("allows SystemAuditor audit log read and denies export", () => {
    expect(canAccessAuditLogs(["SystemAuditor"])).toBe(true);
    expect(canAccessInstitutionReport(["SystemAuditor"])).toBe(true);
    expect(canExecuteExport(["SystemAuditor"])).toBe(false);
    expect(isSystemAuditor(["SystemAuditor"])).toBe(true);
    expect(isReadOnlyStaffRole(["SystemAuditor"])).toBe(true);
  });

  it("denies audit log access for students", () => {
    expect(canAccessAuditLogs(["Student"])).toBe(false);
  });

  it("gates session control nav for lecturer and admin only — AC-23 NFR-09", () => {
    expect(canAccessSessionControl(["Lecturer"])).toBe(true);
    expect(canAccessSessionControl(["AcademicAdmin"])).toBe(true);
    expect(canAccessSessionControl(["Student"])).toBe(false);
    expect(canAccessSessionControl(["SystemAuditor"])).toBe(false);
  });
});
