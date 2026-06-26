import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ApiError } from "../errors/api-error.js";
import {
  assertRolePermission,
  roleHasCapability,
} from "./permissions.js";
import type { JwtPayload } from "./types.js";

describe("role permissions (FR-25)", () => {
  const admin: JwtPayload = {
    sub: "admin-1",
    role: "OrganizerAdmin",
  };
  const staff: JwtPayload = {
    sub: "staff-1",
    role: "OrganizerStaff",
    assignedEventIds: [],
  };
  const participant: JwtPayload = {
    sub: "participant-1",
    role: "Participant",
  };

  it("OrganizerAdmin may create events", () => {
    assert.equal(roleHasCapability("OrganizerAdmin", "event.create"), true);
    assert.doesNotThrow(() => assertRolePermission(admin, "event.create"));
  });

  it("OrganizerStaff and Participant cannot create events", () => {
    assert.equal(roleHasCapability("OrganizerStaff", "event.create"), false);
    assert.equal(roleHasCapability("Participant", "event.create"), false);

    for (const actor of [staff, participant]) {
      assert.throws(
        () => assertRolePermission(actor, "event.create"),
        (error: unknown) =>
          error instanceof ApiError &&
          error.code === "FORBIDDEN" &&
          error.statusCode === 403,
      );
    }
  });

  it("Participant may register; organizers may not self-register via API", () => {
    assert.doesNotThrow(() =>
      assertRolePermission(participant, "registration.register"),
    );
    assert.throws(() => assertRolePermission(admin, "registration.register"));
    assert.throws(() => assertRolePermission(staff, "registration.register"));
  });

  it("audit.read is OrganizerAdmin only", () => {
    assert.doesNotThrow(() => assertRolePermission(admin, "audit.read"));
    assert.throws(() => assertRolePermission(staff, "audit.read"));
    assert.throws(() => assertRolePermission(participant, "audit.read"));
  });

  it("FR-20: eligibility.revoke is OrganizerAdmin only", () => {
    assert.doesNotThrow(() => assertRolePermission(admin, "eligibility.revoke"));
    assert.throws(() => assertRolePermission(staff, "eligibility.revoke"));
    assert.throws(() => assertRolePermission(participant, "eligibility.revoke"));
  });

  it("FR-24: export.reports is OrganizerAdmin only", () => {
    assert.doesNotThrow(() => assertRolePermission(admin, "export.reports"));
    assert.throws(() => assertRolePermission(staff, "export.reports"));
    assert.throws(() => assertRolePermission(participant, "export.reports"));
  });
});
