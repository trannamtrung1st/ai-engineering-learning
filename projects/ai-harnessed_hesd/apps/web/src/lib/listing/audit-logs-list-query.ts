export interface AuditLogsListQuery {
  search?: string;
  actorUserId?: string;
  targetType?: string;
  targetId?: string;
  classSessionId?: string;
  actionType?: string;
  from?: string;
  to?: string;
  sortBy: "timestamp";
  sortOrder: "asc" | "desc";
  page: number;
  pageSize: number;
}

export const DEFAULT_AUDIT_LOGS_QUERY: AuditLogsListQuery = {
  sortBy: "timestamp",
  sortOrder: "desc",
  page: 1,
  pageSize: 25,
};

export function parseAuditLogsListQuery(searchParams: URLSearchParams): AuditLogsListQuery {
  const page = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const pageSize = Number.parseInt(searchParams.get("pageSize") ?? "25", 10);
  const sortOrder = searchParams.get("sortOrder");

  return {
    search: searchParams.get("search") ?? undefined,
    actorUserId: searchParams.get("actorUserId") ?? undefined,
    targetType: searchParams.get("targetType") ?? undefined,
    targetId: searchParams.get("targetId") ?? undefined,
    classSessionId: searchParams.get("classSessionId") ?? undefined,
    actionType: searchParams.get("actionType") ?? undefined,
    from: searchParams.get("from") ?? undefined,
    to: searchParams.get("to") ?? undefined,
    sortBy: "timestamp",
    sortOrder: sortOrder === "asc" ? "asc" : "desc",
    page: Number.isFinite(page) && page > 0 ? page : 1,
    pageSize: Number.isFinite(pageSize) && pageSize > 0 ? pageSize : 25,
  };
}

export function auditLogsQueryToSearchParams(state: AuditLogsListQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (state.search) params.set("search", state.search);
  if (state.actorUserId) params.set("actorUserId", state.actorUserId);
  if (state.targetType) params.set("targetType", state.targetType);
  if (state.targetId) params.set("targetId", state.targetId);
  if (state.classSessionId) params.set("classSessionId", state.classSessionId);
  if (state.actionType) params.set("actionType", state.actionType);
  if (state.from) params.set("from", state.from);
  if (state.to) params.set("to", state.to);
  params.set("sortBy", state.sortBy);
  params.set("sortOrder", state.sortOrder);
  params.set("page", String(state.page));
  params.set("pageSize", String(state.pageSize));
  return params;
}
