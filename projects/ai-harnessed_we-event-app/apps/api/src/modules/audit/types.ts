export interface AuditWriteInput {
  eventId: string;
  entityType: string;
  entityId: string;
  action: string;
  actorId: string;
  actorRole: string;
  reasonCode?: string | null;
  reasonText?: string | null;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
}

export interface AuditLogRow {
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
}

export interface AuditLogEntry {
  id: string;
  eventId: string;
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
}

export interface StatusHistoryEntry {
  id: string;
  registrationId: string;
  action: string;
  actorId: string;
  actorRole: string;
  reasonCode: string | null;
  reasonText: string | null;
  beforeState: string | null;
  afterState: string | null;
  occurredAt: string;
}

export interface ListAuditLogsQuery {
  entityType?: string;
  entityId?: string;
  limit?: number;
}

export interface ListStatusHistoryQuery {
  registrationId?: string;
  limit?: number;
}
