import type { ApiEnvelope } from "@attendly/domain";
import type { PaginationMeta } from "./attendance-history-api.js";
import type { AuditLogsListQuery } from "../listing/audit-logs-list-query.js";
import { apiRequest } from "./client.js";

export interface AuditLogEntry {
  id: string;
  actionType: string;
  actorUserId: string | null;
  actorRole: string | null;
  actorDisplayName: string | null;
  targetType: string;
  targetId: string;
  studentUserId: string | null;
  classSessionId: string | null;
  classSectionId: string | null;
  oldStatus: string | null;
  newStatus: string | null;
  outcome: string | null;
  reason: string | null;
  scopeFilterSummary: string | null;
  format: string | null;
  correlationId: string | null;
  occurredAt: string;
}

export type AuditLogsResult =
  | { ok: true; items: AuditLogEntry[]; pagination: PaginationMeta }
  | { ok: false; code: string; message: string };

function buildAuditParams(query: AuditLogsListQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.actorUserId) params.set("actorUserId", query.actorUserId);
  if (query.targetType) params.set("targetType", query.targetType);
  if (query.targetId) params.set("targetId", query.targetId);
  if (query.classSessionId) params.set("classSessionId", query.classSessionId);
  if (query.actionType) params.set("actionType", query.actionType);
  if (query.from) params.set("from", query.from);
  if (query.to) params.set("to", query.to);
  params.set("page", String(query.page));
  params.set("pageSize", String(query.pageSize));
  return params;
}

export async function fetchAuditLogs(query: AuditLogsListQuery): Promise<AuditLogsResult> {
  const envelope = await apiRequest<AuditLogEntry[]>(
    `/audit-logs?${buildAuditParams(query).toString()}`,
  );

  if (envelope.data && !envelope.error) {
    const meta = envelope.meta as ApiEnvelope<AuditLogEntry[]>["meta"] & {
      pagination?: PaginationMeta;
    };
    if (!meta.pagination) {
      return {
        ok: false,
        code: "InvalidResponse",
        message: "Thiếu thông tin phân trang nhật ký audit.",
      };
    }
    return { ok: true, items: envelope.data, pagination: meta.pagination };
  }

  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải nhật ký audit.",
  };
}
