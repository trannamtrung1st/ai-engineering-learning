import type { PaginatedQuery } from "../../pagination/index.js";

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

export interface ListAuditLogsQuery extends PaginatedQuery {
  entityType?: string;
  entityId?: string;
  sort?: string;
}

export interface ListStatusHistoryQuery extends PaginatedQuery {
  registrationId?: string;
  sort?: string;
}

export interface ListAuditLogsOptions {
  entityType?: string;
  entityId?: string;
  sortColumn: string;
  sortDirection: "ASC" | "DESC";
  limit: number;
  offset: number;
}

export interface ListStatusHistoryOptions {
  registrationId?: string;
  sortColumn: string;
  sortDirection: "ASC" | "DESC";
  limit: number;
  offset: number;
}

export interface ListAuditLogsResult {
  items: AuditLogRow[];
  total: number;
}

export interface ListStatusHistoryResult {
  items: AuditLogRow[];
  total: number;
}
