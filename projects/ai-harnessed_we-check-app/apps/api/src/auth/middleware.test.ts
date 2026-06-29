import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { SESSION_COOKIE_NAME, UserRole } from "@wecheck/domain";
import { extractSessionId } from "./middleware.js";
import {
  Permission,
  RBAC_DENIED_MATRIX,
  assertPermission,
  roleHasPermission,
} from "./permissions.js";

/**
 * Traceability: FR-02 FR-03 NFR-10 NFR-11 NFR-16 AC-03 AC-12 AC-13 AC-14
 */
describe("auth middleware helpers (FR-02, NFR-10)", () => {
  it("extracts session id from wecheck_session cookie (TC-FR-02-010)", () => {
    const sessionId = "550e8400-e29b-41d4-a716-446655440000";
    const request = {
      cookies: { [SESSION_COOKIE_NAME]: sessionId },
      headers: {},
    };
    assert.equal(extractSessionId(request as never), sessionId);
  });

  it("extracts session id from Authorization Bearer header (TC-FR-02-010)", () => {
    const sessionId = "6ba7b810-9dad-11d1-80b4-00c04fd430c8";
    const request = {
      cookies: {},
      headers: { authorization: `Bearer ${sessionId}` },
    };
    assert.equal(extractSessionId(request as never), sessionId);
  });

  it("rejects malformed session identifiers (TC-NFR-10-012)", () => {
    const request = {
      cookies: { [SESSION_COOKIE_NAME]: "not-a-valid-uuid" },
      headers: { authorization: "Bearer invalid-token-value" },
    };
    assert.equal(extractSessionId(request as never), null);
  });

  it("returns null when no credentials present (TC-FR-02-014)", () => {
    const request = { cookies: {}, headers: {} };
    assert.equal(extractSessionId(request as never), null);
  });
});

describe("permission guard matrix (NFR-11)", () => {
  it("grants checkin:submit to Student only (TC-FR-02-011)", () => {
    assert.equal(roleHasPermission(UserRole.Student, Permission.CheckinSubmit), true);
    assert.equal(roleHasPermission(UserRole.Instructor, Permission.CheckinSubmit), false);
    assert.equal(
      roleHasPermission(UserRole.TrainingOfficeAdmin, Permission.CheckinSubmit),
      false,
    );
  });

  it("grants report:export to TrainingOfficeAdmin only (TC-NFR-11-005)", () => {
    assert.equal(roleHasPermission(UserRole.TrainingOfficeAdmin, Permission.ReportExport), true);
    assert.equal(roleHasPermission(UserRole.Instructor, Permission.ReportExport), false);
    assert.equal(roleHasPermission(UserRole.Student, Permission.ReportExport), false);
  });

  it("denies matrix permissions for Student role (TC-NFR-11-010, TC-NFR-11-020)", () => {
    for (const permission of RBAC_DENIED_MATRIX[UserRole.Student]) {
      assert.equal(
        assertPermission(UserRole.Student, permission),
        false,
        `Student should not have ${permission}`,
      );
    }
  });

  it("denies checkin:submit and report:export for Instructor (TC-NFR-11-011)", () => {
    assert.equal(assertPermission(UserRole.Instructor, Permission.CheckinSubmit), false);
    assert.equal(assertPermission(UserRole.Instructor, Permission.ReportExport), false);
    assert.equal(assertPermission(UserRole.Instructor, Permission.RosterWrite), false);
  });

  it("denies checkin:submit and qr:display for Admin (TC-NFR-11-020)", () => {
    assert.equal(
      assertPermission(UserRole.TrainingOfficeAdmin, Permission.CheckinSubmit),
      false,
    );
    assert.equal(
      assertPermission(UserRole.TrainingOfficeAdmin, Permission.QrDisplay),
      false,
    );
  });
});
