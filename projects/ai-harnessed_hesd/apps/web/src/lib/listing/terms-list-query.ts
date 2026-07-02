export interface TermsListQueryState {
  search?: string;
  activeOnly?: boolean;
  sortOrder: "asc" | "desc";
  page: number;
  pageSize: number;
}

export const DEFAULT_TERMS_LIST_QUERY: TermsListQueryState = {
  sortOrder: "asc",
  page: 1,
  pageSize: 25,
};

export function parseTermsListQuery(searchParams: URLSearchParams): TermsListQueryState {
  const page = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const pageSize = Number.parseInt(searchParams.get("pageSize") ?? "25", 10);

  return {
    search: searchParams.get("search") ?? undefined,
    activeOnly: searchParams.get("activeOnly") === "true" ? true : undefined,
    sortOrder: (searchParams.get("sortOrder") as "asc" | "desc") ?? DEFAULT_TERMS_LIST_QUERY.sortOrder,
    page: Number.isFinite(page) && page > 0 ? page : 1,
    pageSize: Number.isFinite(pageSize) && pageSize > 0 ? pageSize : 25,
  };
}

export function termsListQueryToSearchParams(state: TermsListQueryState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.search) params.set("search", state.search);
  if (state.activeOnly) params.set("activeOnly", "true");
  params.set("sortOrder", state.sortOrder);
  params.set("page", String(state.page));
  params.set("pageSize", String(state.pageSize));
  return params;
}
