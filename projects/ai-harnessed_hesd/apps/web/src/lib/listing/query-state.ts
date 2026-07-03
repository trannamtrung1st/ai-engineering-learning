export interface ListingQueryState {
  termId?: string;
  classSectionId?: string;
  search?: string;
  status?: string;
  from?: string;
  to?: string;
  sortBy: string;
  sortOrder: "asc" | "desc";
  page: number;
  pageSize: number;
}

export const DEFAULT_LISTING_QUERY: ListingQueryState = {
  sortBy: "date",
  sortOrder: "desc",
  page: 1,
  pageSize: 25,
};

export function parseListingQuery(searchParams: URLSearchParams): ListingQueryState {
  const page = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const pageSize = Number.parseInt(searchParams.get("pageSize") ?? "25", 10);

  return {
    termId: searchParams.get("termId") ?? undefined,
    classSectionId: searchParams.get("classSectionId") ?? undefined,
    search: searchParams.get("search") ?? undefined,
    status: searchParams.get("status") ?? undefined,
    from: searchParams.get("from") ?? undefined,
    to: searchParams.get("to") ?? undefined,
    sortBy: searchParams.get("sortBy") ?? DEFAULT_LISTING_QUERY.sortBy,
    sortOrder: (searchParams.get("sortOrder") as "asc" | "desc") ?? DEFAULT_LISTING_QUERY.sortOrder,
    page: Number.isFinite(page) && page > 0 ? page : 1,
    pageSize: Number.isFinite(pageSize) && pageSize > 0 ? pageSize : 25,
  };
}

export function listingQueryToSearchParams(state: ListingQueryState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.termId) params.set("termId", state.termId);
  if (state.classSectionId) params.set("classSectionId", state.classSectionId);
  if (state.search) params.set("search", state.search);
  if (state.status) params.set("status", state.status);
  if (state.from) params.set("from", state.from);
  if (state.to) params.set("to", state.to);
  params.set("sortBy", state.sortBy);
  params.set("sortOrder", state.sortOrder);
  params.set("page", String(state.page));
  params.set("pageSize", String(state.pageSize));
  return params;
}

export function buildListingQueryString(state: ListingQueryState): string {
  const params = listingQueryToSearchParams(state);
  const query = params.toString();
  return query.length > 0 ? `?${query}` : "";
}
