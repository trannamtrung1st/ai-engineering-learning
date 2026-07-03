import { describe, expect, it, beforeEach } from "vitest";
import {
  buildLoginRedirect,
  clearStudentAuthentication,
  isStudentAuthenticated,
  markStudentAuthenticated,
  preserveCheckInDeepLink,
  requiresCheckInAuth,
  resolveReturnUrl,
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
});
