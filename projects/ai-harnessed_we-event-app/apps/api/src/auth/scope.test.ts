import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ApiError } from "../errors/api-error.js";
import { resolveActorId } from "./resolve-actor-id.js";
import {
  assertEventScope,
  assertParticipantOwnership,
} from "./scope.js";
import type { JwtPayload } from "./types.js";

describe("participant scope", () => {
  const participantSub = "participant-a";
  const participantId = resolveActorId(participantSub);

  const participantActor: JwtPayload = {
    sub: participantSub,
    role: "Participant",
  };

  it("FR-26: participant may access own registration data", () => {
    assert.doesNotThrow(() =>
      assertParticipantOwnership(participantActor, participantId),
    );
    assert.doesNotThrow(() =>
      assertParticipantOwnership(participantActor, participantSub),
    );
  });

  it("FR-26: participant cannot access another participant's data", () => {
    assert.throws(
      () =>
        assertParticipantOwnership(participantActor, resolveActorId("participant-b")),
      (error: unknown) =>
        error instanceof ApiError &&
        error.code === "FORBIDDEN" &&
        error.statusCode === 403,
    );
  });

  it("organizer roles bypass participant ownership check", () => {
    const admin: JwtPayload = { sub: "admin-1", role: "OrganizerAdmin" };
    assert.doesNotThrow(() =>
      assertParticipantOwnership(admin, resolveActorId("participant-b")),
    );
  });
});

describe("event scope", () => {
  const eventId = "00000000-0000-0000-0000-000000000010";

  it("FR-25: OrganizerAdmin has unrestricted event access", () => {
    const admin: JwtPayload = { sub: "admin-1", role: "OrganizerAdmin" };
    assert.doesNotThrow(() => assertEventScope(admin, eventId));
  });

  it("FR-25: OrganizerStaff limited to assigned events", () => {
    const staff: JwtPayload = {
      sub: "staff-1",
      role: "OrganizerStaff",
      assignedEventIds: [eventId],
    };
    assert.doesNotThrow(() => assertEventScope(staff, eventId));

    assert.throws(
      () =>
        assertEventScope(staff, "00000000-0000-0000-0000-000000000099"),
      (error: unknown) =>
        error instanceof ApiError && error.code === "FORBIDDEN",
    );
  });

  it("FR-25: Participant cannot access organizer event scope routes", () => {
    const participant: JwtPayload = { sub: "p-1", role: "Participant" };
    assert.throws(
      () => assertEventScope(participant, eventId),
      (error: unknown) =>
        error instanceof ApiError && error.code === "FORBIDDEN",
    );
  });
});
