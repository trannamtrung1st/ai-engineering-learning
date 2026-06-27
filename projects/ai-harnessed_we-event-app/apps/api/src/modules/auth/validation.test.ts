import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ApiError } from "../../errors/api-error.js";
import type { UserRoleRow } from "../user/types.js";
import {
  selectJwtRole,
  validateLoginInput,
  validateRegisterInput,
} from "./validation.js";

describe("auth validation", () => {
  it("validates register input", () => {
    const result = validateRegisterInput({
      email: "User@Example.com",
      password: "password123",
      displayName: "Test User",
    });
    assert.equal(result.email, "user@example.com");
    assert.equal(result.displayName, "Test User");
  });

  it("rejects short passwords on register", () => {
    assert.throws(
      () =>
        validateRegisterInput({
          email: "user@example.com",
          password: "short",
          displayName: "Test User",
        }),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, "INVALID_INPUT");
        assert.equal(error.statusCode, 400);
        return true;
      },
    );
  });

  it("validates login input", () => {
    const result = validateLoginInput({
      email: "user@example.com",
      password: "password123",
    });
    assert.equal(result.email, "user@example.com");
  });

  it("NFR-08: selects highest-privilege JWT role", () => {
    const roles: UserRoleRow[] = [
      {
        id: "1",
        userId: "user-1",
        role: "Participant",
        organizationId: null,
        assignedEventIds: [],
      },
      {
        id: "2",
        userId: "user-1",
        role: "OrganizerAdmin",
        organizationId: "org-1",
        assignedEventIds: [],
      },
    ];

    const selected = selectJwtRole(roles);
    assert.equal(selected.role, "OrganizerAdmin");
  });

  it("FR-26: defaults to Participant when no organizer roles", () => {
    const roles: UserRoleRow[] = [
      {
        id: "1",
        userId: "user-1",
        role: "Participant",
        organizationId: null,
        assignedEventIds: [],
      },
    ];

    const selected = selectJwtRole(roles);
    assert.equal(selected.role, "Participant");
    assert.deepEqual(selected.assignedEventIds, []);
  });
});
