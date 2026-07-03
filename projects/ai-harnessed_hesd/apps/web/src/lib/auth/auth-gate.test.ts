import { describe, expect, it, beforeEach } from "vitest";
import {
  buildLoginRedirect,
  clearStudentAuthentication,
  isStudentAuthenticated,
  markStudentAuthenticated,
  preserveCheckInDeepLink,
  requiresCheckInAuth,
  resolveReturnUrl,
  resolveRoleHomePath,
  resolvePostLoginPath,
} from "./auth-gate";

describe("auth gate (NFR-14 FR-15)", () => {
  beforeEach(() => {
    clearStudentAuthentication();
  });

  it("preserves check-in deep link in login redirect", () => {
    const path = preserveCheckInDeepLink("/check-in", "?token=demo");
    const result = buildLoginRedirect(path);
    expect(result.redirectTo).toBe("/login?returnUrl=%2Fcheck-in%3Ftoken%3Ddemo");
    expect(result.message).toContain("Đăng nhập");
  });

  it("resolves safe internal return URLs", () => {
    const params = new URLSearchParams("returnUrl=%2Fcheck-in%3Ftoken%3Ddemo");
    expect(resolveReturnUrl(params)).toBe("/check-in?token=demo");
  });

  it("rejects external return URLs", () => {
    const params = new URLSearchParams("returnUrl=https%3A%2F%2Fevil.test");
    expect(resolveReturnUrl(params, "/")).toBe("/");
  });

  it("TC-NFR-14-010: gates token deep links until student authenticates", () => {
    const params = new URLSearchParams("token=validToken");
    expect(requiresCheckInAuth(params)).toBe(true);
    expect(isStudentAuthenticated()).toBe(false);

    markStudentAuthenticated();
    expect(isStudentAuthenticated()).toBe(true);
    expect(requiresCheckInAuth(params)).toBe(true);
  });

  it("allows outcome preview routes without authentication", () => {
    const params = new URLSearchParams("outcome=expired-qr");
    expect(requiresCheckInAuth(params)).toBe(false);
  });

  it("TC-UX-COMMON-005: resolves role home when login has no returnUrl", () => {
    expect(resolveRoleHomePath(["Lecturer"])).toBe("/lecturer/sessions");
    expect(resolveRoleHomePath(["AcademicAdmin"])).toBe("/admin/terms");
    expect(resolveRoleHomePath(["Student"])).toBe("/check-in");
    expect(resolveRoleHomePath(["SystemAuditor"])).toBe("/audit/logs");
  });

  it("TC-UX-COMMON-005: honors returnUrl over role home on deep-link login", () => {
    const params = new URLSearchParams("returnUrl=%2Fcheck-in%3Ftoken%3Ddemo");
    expect(resolvePostLoginPath(["Lecturer"], params)).toBe("/check-in?token=demo");
  });

  it("FLOW-15: voluntary login without returnUrl uses role home", () => {
    const params = new URLSearchParams();
    expect(resolvePostLoginPath(["Lecturer"], params)).toBe("/lecturer/sessions");
    expect(resolvePostLoginPath(["AcademicAdmin"], params)).toBe("/admin/terms");
  });
});
