import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ErrorCode, UserRole } from "@wecheck/domain";
import {
  validateCreateUserBody,
  validateEmail,
  validateInstitutionalId,
  validateLoginBody,
  validatePassword,
  validateReturnUrl,
  validateSessionInactivityHours,
  validateUpdateUserBody,
} from "./validation.js";

/**
 * Traceability: AC-01 AC-02 FR-01 FR-02 BR-06 NFR-14 NFR-16
 * Cases: TC-NFR-14-005 TC-NFR-14-012 TC-AC-01-004 TC-AC-02-009
 */
describe("identity-auth validation (AC-01, AC-02, FR-01, FR-02, NFR-14)", () => {
  it("validateEmail normalizes and accepts valid email (VAL-02)", () => {
    const result = validateEmail("  Student@Example.Edu.VN  ");
    assert.equal(result.ok, true);
    if (result.ok) {
      assert.equal(result.value, "student@example.edu.vn");
    }
  });

  it("validateEmail rejects invalid format", () => {
    const result = validateEmail("not-an-email");
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(result.details[0]?.code, ErrorCode.InvalidEmail);
    }
  });

  it("validatePassword enforces min 8 chars (VAL-03, NFR-14)", () => {
    const short = validatePassword("short12");
    assert.equal(short.ok, false);
    if (!short.ok) {
      assert.equal(short.details[0]?.code, ErrorCode.PasswordTooShort);
    }

    const ok = validatePassword("exactly8");
    assert.equal(ok.ok, true);
  });

  it("validatePassword rejects passwords over 128 chars (NFR-14)", () => {
    const long = "a".repeat(129);
    const result = validatePassword(long);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(result.details[0]?.code, ErrorCode.InvalidLength);
    }
  });

  it("validateInstitutionalId enforces pattern (VAL-05)", () => {
    const bad = validateInstitutionalId("ab");
    assert.equal(bad.ok, false);

    const good = validateInstitutionalId("SV2026001");
    assert.equal(good.ok, true);
  });

  it("validateReturnUrl blocks open redirects (VAL-09)", () => {
    assert.equal(validateReturnUrl("//evil.com").ok, false);
    assert.equal(validateReturnUrl("/check-in?token=abc").ok, true);
  });

  it("validateLoginBody requires email and password (FR-02)", () => {
    const missing = validateLoginBody({ email: "a@b.c" });
    assert.equal(missing.ok, false);

    const ok = validateLoginBody({
      email: "student@example.edu.vn",
      password: "secret123",
      returnUrl: "/check-in?token=x",
    });
    assert.equal(ok.ok, true);
    if (ok.ok) {
      assert.equal(ok.value.returnUrl, "/check-in?token=x");
    }
  });

  it("validateCreateUserBody requires all fields (FR-01)", () => {
    const result = validateCreateUserBody({
      institutionalId: "SV2026999",
      displayName: "Nguyễn Văn A",
      email: "new@example.edu.vn",
      password: "StudentPass8",
      role: UserRole.Student,
    });
    assert.equal(result.ok, true);
  });

  it("validateCreateUserBody rejects short password (TC-NFR-14-005)", () => {
    const result = validateCreateUserBody({
      institutionalId: "SV2026998",
      displayName: "Test",
      email: "short@example.edu.vn",
      password: "short12",
      role: UserRole.Student,
    });
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(
        result.details.some((d) => d.code === ErrorCode.PasswordTooShort),
        true,
      );
    }
  });

  it("validateUpdateUserBody accepts partial updates (FR-01)", () => {
    const result = validateUpdateUserBody({ displayName: "Updated Name" });
    assert.equal(result.ok, true);
    if (result.ok) {
      assert.equal(result.value.displayName, "Updated Name");
    }
  });

  it("validateSessionInactivityHours enforces 4-12 range (NFR-16)", () => {
    assert.equal(validateSessionInactivityHours({ inactivityHours: 3 }).ok, false);
    assert.equal(validateSessionInactivityHours({ inactivityHours: 13 }).ok, false);
    assert.equal(validateSessionInactivityHours({ inactivityHours: 8 }).ok, true);
    assert.equal(validateSessionInactivityHours({ inactivityHours: 10 }).ok, true);
  });
});
