import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { UserRole } from "@wecheck/domain";
import {
  Permission,
  RBAC_DENIED_MATRIX,
  assertPermission,
  roleHasPermission,
} from "./permissions.js";

/**
 * Traceability: NFR-11 FR-03 FR-12 FR-13 AC-03 AC-12 AC-13 AC-14 BR-08 BR-09
 */
describe("permissions RBAC matrix (NFR-11)", () => {
  it("Student never receives report:read (TC-NFR-11-009)", () => {
    assert.equal(roleHasPermission(UserRole.Student, Permission.ReportRead), false);
  });

  it("Instructor receives scoped report:read (TC-NFR-11-004)", () => {
    assert.equal(roleHasPermission(UserRole.Instructor, Permission.ReportRead), true);
  });

  it("TrainingOfficeAdmin receives institution-wide report permissions (TC-NFR-11-005)", () => {
    assert.equal(
      roleHasPermission(UserRole.TrainingOfficeAdmin, Permission.ReportRead),
      true,
    );
    assert.equal(
      roleHasPermission(UserRole.TrainingOfficeAdmin, Permission.ReportExport),
      true,
    );
  });

  it("Student lacks roster:read for enrollment views (TC-NFR-11-006, AC-03, FR-03)", () => {
    assert.equal(roleHasPermission(UserRole.Student, Permission.RosterRead), false);
  });

  it("Instructor receives roster:read for scoped enrollment (TC-NFR-11-006, AC-03)", () => {
    assert.equal(roleHasPermission(UserRole.Instructor, Permission.RosterRead), true);
  });

  it("Student attendance:read limited to self scope (TC-NFR-11-013, AC-14)", () => {
    assert.equal(roleHasPermission(UserRole.Student, Permission.AttendanceRead), true);
    assert.equal(roleHasPermission(UserRole.Student, Permission.AttendanceWrite), false);
  });

  it("100% denial rate for RBAC negative matrix sample (TC-NFR-11-020)", () => {
    let denied = 0;
    let total = 0;
    for (const [role, permissions] of Object.entries(RBAC_DENIED_MATRIX)) {
      for (const permission of permissions) {
        total += 1;
        if (!assertPermission(role as UserRole, permission)) {
          denied += 1;
        }
      }
    }
    assert.ok(total > 0);
    assert.equal(denied, total);
  });
});
