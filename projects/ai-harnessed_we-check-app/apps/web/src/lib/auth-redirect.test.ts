import { describe, expect, it } from "vitest";
import { UserRole } from "@wecheck/domain";
import {
  currentPathWithSearch,
  getRoleHome,
  isSafeReturnUrl,
  loginReturnUrl,
  resolvePostLoginRedirect,
} from "@/lib/auth-redirect";

/** AC-02 / FR-02 / BR-06 / NFR-16 — auth redirect and returnUrl safety */
describe("auth-redirect (AC-02, FR-02, BR-06, NFR-16)", () => {
  it("maps each role to its default home route", () => {
    expect(getRoleHome(UserRole.Student)).toBe("/check-in");
    expect(getRoleHome(UserRole.Instructor)).toBe("/sessions");
    expect(getRoleHome(UserRole.TrainingOfficeAdmin)).toBe("/admin/users");
  });

  it("accepts safe relative returnUrl paths (BR-06)", () => {
    expect(isSafeReturnUrl("/check-in?token=abc")).toBe(true);
    expect(isSafeReturnUrl("/sessions/sess-1")).toBe(true);
  });

  it("rejects open redirects and login loops (VAL-09)", () => {
    expect(isSafeReturnUrl("https://evil.test")).toBe(false);
    expect(isSafeReturnUrl("//evil.test/path")).toBe(false);
    expect(isSafeReturnUrl("/login")).toBe(false);
    expect(isSafeReturnUrl("/login?returnUrl=/check-in")).toBe(false);
    expect(isSafeReturnUrl(null)).toBe(false);
  });

  it("prefers redirectTo over returnUrl when both are safe (TC-AC-02-002)", () => {
    expect(
      resolvePostLoginRedirect(UserRole.Student, {
        returnUrl: "/history",
        redirectTo: "/check-in?token=test",
      }),
    ).toBe("/check-in?token=test");
  });

  it("falls back to role home when returnUrl is unsafe", () => {
    expect(
      resolvePostLoginRedirect(UserRole.Instructor, {
        returnUrl: "https://evil.test",
      }),
    ).toBe("/sessions");
  });

  it("builds login URL with encoded returnUrl (AC-02a)", () => {
    expect(loginReturnUrl("/check-in?token=stale-token-id")).toBe(
      "/login?returnUrl=%2Fcheck-in%3Ftoken%3Dstale-token-id",
    );
  });

  it("adds sessionExpired flag for idle timeout redirect (AC-02c, NFR-16)", () => {
    expect(
      loginReturnUrl("/check-in?token=x", { sessionExpired: true }),
    ).toBe("/login?returnUrl=%2Fcheck-in%3Ftoken%3Dx&sessionExpired=1");
  });

  it("preserves pathname and search for return path helper", () => {
    expect(
      currentPathWithSearch({
        pathname: "/check-in",
        search: "?token=abc",
      }),
    ).toBe("/check-in?token=abc");
  });
});
