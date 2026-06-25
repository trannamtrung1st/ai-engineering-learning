import { ApiError } from "../../errors/api-error.js";
import {
  buildPaginatedResult,
  parsePagination,
  parseSort,
  type PaginatedResult,
} from "../../pagination/index.js";
import { findEventById } from "../event/repository.js";
import {
  listAuditLogsForEvent,
  listRegistrationStatusHistory,
} from "./repository.js";
import type {
  AuditLogEntry,
  ListAuditLogsQuery,
  ListStatusHistoryQuery,
  StatusHistoryEntry,
} from "./types.js";

function toAuditLogEntry(row: {
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

function extractState(value: unknown): string | null {
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

function toStatusHistoryEntry(row: {
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

export class AuditService {
  async listAuditLogs(
    eventId: string,
    query: ListAuditLogsQuery = {},
  ): Promise<PaginatedResult<AuditLogEntry>> {
    await this.requireEvent(eventId);

    const pagination = parsePagination(query, {
      defaultPageSize: 20,
      maxPageSize: 100,
    });

    const sort = parseSort(
      query.sort,
      { createdAt: "occurred_at" },
      "createdAt",
    );

    const effectiveSort = query.sort?.trim()
      ? sort
      : { column: "occurred_at", direction: "DESC" as const };

    const { items, total } = await listAuditLogsForEvent(eventId, {
      entityType: query.entityType,
      entityId: query.entityId,
      sortColumn: effectiveSort.column,
      sortDirection: effectiveSort.direction,
      limit: pagination.pageSize,
      offset: pagination.offset,
    });

    return buildPaginatedResult(
      items.map(toAuditLogEntry),
      total,
      pagination,
    );
  }

  async listStatusHistory(
    eventId: string,
    query: ListStatusHistoryQuery = {},
  ): Promise<PaginatedResult<StatusHistoryEntry>> {
    await this.requireEvent(eventId);

    const pagination = parsePagination(query, {
      defaultPageSize: 20,
      maxPageSize: 100,
    });

    const sort = parseSort(
      query.sort,
      { createdAt: "occurred_at" },
      "createdAt",
    );

    const effectiveSort = query.sort?.trim()
      ? sort
      : { column: "occurred_at", direction: "DESC" as const };

    const { items, total } = await listRegistrationStatusHistory(eventId, {
      registrationId: query.registrationId,
      sortColumn: effectiveSort.column,
      sortDirection: effectiveSort.direction,
      limit: pagination.pageSize,
      offset: pagination.offset,
    });

    return buildPaginatedResult(
      items.map(toStatusHistoryEntry),
      total,
      pagination,
    );
  }

  private async requireEvent(eventId: string): Promise<void> {
    const event = await findEventById(eventId);
    if (!event) {
      throw new ApiError({
        code: "NOT_FOUND",
        message: "Event not found.",
        statusCode: 404,
        details: { eventId },
      });
    }
  }
}

export const auditService = new AuditService();
