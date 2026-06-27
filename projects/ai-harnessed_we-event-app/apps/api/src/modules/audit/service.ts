import { ApiError } from "../../errors/api-error.js";
import {
  buildPaginatedResult,
  parsePagination,
  parseSort,
  type PaginatedResult,
} from "../../pagination/index.js";
import { findEventById } from "../event/repository.js";
import { toAuditLogEntry, toStatusHistoryEntry } from "./mappers.js";
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
