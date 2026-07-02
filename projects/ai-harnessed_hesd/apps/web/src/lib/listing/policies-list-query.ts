import type { PolicyScopeType, PolicySummary } from "../api/policy-api.js";
import { resolvePolicyScopeName, type ScopeNameLookup } from "../api/policy-api.js";

export interface PoliciesListQueryState {
  search?: string;
  scopeLevel?: PolicyScopeType;
  sortOrder: "asc" | "desc";
  page: number;
  pageSize: number;
}

export const DEFAULT_POLICIES_LIST_QUERY: PoliciesListQueryState = {
  sortOrder: "desc",
  page: 1,
  pageSize: 25,
};

const SCOPE_LEVELS: PolicyScopeType[] = ["Institution", "Faculty", "Course", "ClassSection"];

function isPolicyScopeType(value: string): value is PolicyScopeType {
  return (SCOPE_LEVELS as string[]).includes(value);
}

export function parsePoliciesListQuery(searchParams: URLSearchParams): PoliciesListQueryState {
  const page = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const pageSize = Number.parseInt(searchParams.get("pageSize") ?? "25", 10);
  const scopeLevelParam = searchParams.get("scopeLevel") ?? undefined;

  return {
    search: searchParams.get("search") ?? undefined,
    scopeLevel: scopeLevelParam && isPolicyScopeType(scopeLevelParam) ? scopeLevelParam : undefined,
    sortOrder: (searchParams.get("sortOrder") as "asc" | "desc") ?? DEFAULT_POLICIES_LIST_QUERY.sortOrder,
    page: Number.isFinite(page) && page > 0 ? page : 1,
    pageSize: Number.isFinite(pageSize) && pageSize > 0 ? pageSize : 25,
  };
}

export function policiesListQueryToSearchParams(state: PoliciesListQueryState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.search) params.set("search", state.search);
  if (state.scopeLevel) params.set("scopeLevel", state.scopeLevel);
  params.set("sortOrder", state.sortOrder);
  params.set("page", String(state.page));
  params.set("pageSize", String(state.pageSize));
  return params;
}

export function sortPolicySummaries(
  items: PolicySummary[],
  sortOrder: PoliciesListQueryState["sortOrder"],
  scopeLookup: ScopeNameLookup,
): PolicySummary[] {
  return [...items].sort((a, b) => {
    const dateCmp = a.createdAt.localeCompare(b.createdAt);
    if (dateCmp !== 0) {
      return sortOrder === "desc" ? -dateCmp : dateCmp;
    }
    const nameCmp = resolvePolicyScopeName(a, scopeLookup).localeCompare(
      resolvePolicyScopeName(b, scopeLookup),
      "vi",
    );
    if (nameCmp !== 0) {
      return sortOrder === "desc" ? -nameCmp : nameCmp;
    }
    const idCmp = a.id.localeCompare(b.id);
    return sortOrder === "desc" ? -idCmp : idCmp;
  });
}
