export interface SessionListQueryState {
  classSectionId?: string;
  state?: string;
  search?: string;
  sortBy: "startTime" | "state";
  sortOrder: "asc" | "desc";
  page: number;
  pageSize: number;
}

export const DEFAULT_SESSION_LIST_QUERY: SessionListQueryState = {
  sortBy: "startTime",
  sortOrder: "desc",
  page: 1,
  pageSize: 25,
};

export function parseSessionListQuery(searchParams: URLSearchParams): SessionListQueryState {
  const page = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const pageSize = Number.parseInt(searchParams.get("pageSize") ?? "25", 10);
  const sortBy = searchParams.get("sortBy") === "state" ? "state" : "startTime";

  return {
    classSectionId: searchParams.get("classSectionId") ?? undefined,
    state: searchParams.get("state") ?? undefined,
    search: searchParams.get("search") ?? undefined,
    sortBy,
    sortOrder: (searchParams.get("sortOrder") as "asc" | "desc") ?? DEFAULT_SESSION_LIST_QUERY.sortOrder,
    page: Number.isFinite(page) && page > 0 ? page : 1,
    pageSize: Number.isFinite(pageSize) && pageSize > 0 ? pageSize : 25,
  };
}

export function sessionListQueryToSearchParams(state: SessionListQueryState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.classSectionId) params.set("classSectionId", state.classSectionId);
  if (state.state) params.set("state", state.state);
  if (state.search) params.set("search", state.search);
  params.set("sortBy", state.sortBy);
  params.set("sortOrder", state.sortOrder);
  params.set("page", String(state.page));
  params.set("pageSize", String(state.pageSize));
  return params;
}

export function buildSessionListQueryString(state: SessionListQueryState): string {
  const query = sessionListQueryToSearchParams(state).toString();
  return query.length > 0 ? `?${query}` : "";
}
