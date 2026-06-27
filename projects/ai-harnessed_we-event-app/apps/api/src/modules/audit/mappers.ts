import type { AuditLogEntry, StatusHistoryEntry } from "./types.js";

export function extractState(value: unknown): string | null {
  if (typeof value === "string") {
    return value;
  }
  if (
    typeof value === "object" &&
    value !== null &&
    "state" in value &&
    typeof (value as { state: unknown }).state === "string"
  ) {
    return (value as { state: string }).state;
  }
  return null;
}

export function toAuditLogEntry(row: {
  id: string;
  eventId: string | null;
  entityType: string;
  entityId: string;
  action: string;
  actorId: string;
  actorRole: string;
  reasonCode: string | null;
  reasonText: string | null;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  occurredAt: string;
}): AuditLogEntry {
  return {
    id: row.id,
    eventId: row.eventId ?? "",
    entityType: row.entityType,
    entityId: row.entityId,
    action: row.action,
    actorId: row.actorId,
    actorRole: row.actorRole,
    reasonCode: row.reasonCode,
    reasonText: row.reasonText,
    before: row.before,
    after: row.after,
    occurredAt: row.occurredAt,
  };
}

export function toStatusHistoryEntry(row: {
  id: string;
  entityType: string;
  entityId: string;
  action: string;
  actorId: string;
  actorRole: string;
  reasonCode: string | null;
  reasonText: string | null;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  occurredAt: string;
}): StatusHistoryEntry {
  const registrationId =
    row.entityType === "Registration"
      ? row.entityId
      : typeof row.after.registrationId === "string"
        ? row.after.registrationId
        : row.entityId;

  return {
    id: row.id,
    registrationId,
    action: row.action,
    actorId: row.actorId,
    actorRole: row.actorRole,
    reasonCode: row.reasonCode,
    reasonText: row.reasonText,
    beforeState: extractState(row.before.state ?? row.before),
    afterState: extractState(row.after.state ?? row.after),
    occurredAt: row.occurredAt,
  };
}
