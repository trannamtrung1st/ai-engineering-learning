export interface ClassSectionsListQueryState {
  termId?: string;
  search?: string;
  sortOrder: "asc" | "desc";
  page: number;
  pageSize: number;
}

export const DEFAULT_CLASS_SECTIONS_LIST_QUERY: ClassSectionsListQueryState = {
  sortOrder: "asc",
  page: 1,
  pageSize: 25,
};

export function parseClassSectionsListQuery(
  searchParams: URLSearchParams,
): ClassSectionsListQueryState {
  const page = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const pageSize = Number.parseInt(searchParams.get("pageSize") ?? "25", 10);

  return {
    termId: searchParams.get("termId") ?? undefined,
    search: searchParams.get("search") ?? undefined,
    sortOrder:
      (searchParams.get("sortOrder") as "asc" | "desc") ??
      DEFAULT_CLASS_SECTIONS_LIST_QUERY.sortOrder,
    page: Number.isFinite(page) && page > 0 ? page : 1,
    pageSize: Number.isFinite(pageSize) && pageSize > 0 ? pageSize : 25,
  };
}

export function classSectionsListQueryToSearchParams(
  state: ClassSectionsListQueryState,
): URLSearchParams {
  const params = new URLSearchParams();
  if (state.termId) params.set("termId", state.termId);
  if (state.search) params.set("search", state.search);
  params.set("sortOrder", state.sortOrder);
  params.set("page", String(state.page));
  params.set("pageSize", String(state.pageSize));
  return params;
}
