import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  extractState,
  toAuditLogEntry,
  toStatusHistoryEntry,
} from "./mappers.js";

describe("audit mappers", () => {
  it("extractState reads plain string or nested state object", () => {
    assert.equal(extractState("Registered"), "Registered");
    assert.equal(extractState({ state: "Waitlisted" }), "Waitlisted");
    assert.equal(extractState({ other: "value" }), null);
    assert.equal(extractState(null), null);
  });

  it("toAuditLogEntry normalizes nullable eventId", () => {
    const entry = toAuditLogEntry({
      id: "00000000-0000-0000-0000-000000000001",
      eventId: null,
      entityType: "Event",
      entityId: "00000000-0000-0000-0000-000000000002",
      action: "event.created",
      actorId: "00000000-0000-0000-0000-000000000099",
      actorRole: "OrganizerAdmin",
      reasonCode: null,
      reasonText: null,
      before: {},
      after: { state: "Draft" },
      occurredAt: "2026-06-24T09:00:00.000Z",
    });

    assert.equal(entry.eventId, "");
    assert.equal(entry.action, "event.created");
    assert.equal(entry.after.state, "Draft");
  });

  it("AC-12: toStatusHistoryEntry maps registration transitions with before/after state", () => {
    const registrationId = "00000000-0000-0000-0000-000000000010";

    const accepted = toStatusHistoryEntry({
      id: "00000000-0000-0000-0000-000000000020",
      entityType: "Registration",
      entityId: registrationId,
      action: "registration.accepted",
      actorId: "00000000-0000-0000-0000-000000000030",
      actorRole: "Participant",
      reasonCode: null,
      reasonText: null,
      before: { state: "Pending" },
      after: { state: "Registered" },
      occurredAt: "2026-06-24T10:00:00.000Z",
    });

    assert.equal(accepted.registrationId, registrationId);
    assert.equal(accepted.beforeState, "Pending");
    assert.equal(accepted.afterState, "Registered");

    const checkin = toStatusHistoryEntry({
      id: "00000000-0000-0000-0000-000000000021",
      entityType: "CheckinRecord",
      entityId: "00000000-0000-0000-0000-000000000040",
      action: "checkin.recorded",
      actorId: "00000000-0000-0000-0000-000000000099",
      actorRole: "OrganizerStaff",
      reasonCode: null,
      reasonText: null,
      before: {},
      after: { registrationId, state: "Attended" },
      occurredAt: "2026-06-24T11:00:00.000Z",
    });

    assert.equal(checkin.registrationId, registrationId);
    assert.equal(checkin.afterState, "Attended");
  });
});
