import { ApiError } from "../errors/api-error.js";

export interface PaginatedQuery {
  page?: string;
  pageSize?: string;
}

export interface PaginationParams {
  page: number;
  pageSize: number;
  offset: number;
}

export interface PaginatedResult<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}

export interface ParsePaginationOptions {
  defaultPageSize: number;
  maxPageSize?: number;
}

export function totalPages(total: number, pageSize: number): number {
  if (total === 0) {
    return 0;
  }
  return Math.ceil(total / pageSize);
}

export function parsePagination(
  query: PaginatedQuery,
  options: ParsePaginationOptions,
): PaginationParams {
  const maxPageSize = options.maxPageSize ?? 100;
  const defaultPageSize = options.defaultPageSize;

  const pageRaw = query.page ?? "1";
  const pageSizeRaw = query.pageSize ?? String(defaultPageSize);

  const page = Number.parseInt(pageRaw, 10);
  const pageSize = Number.parseInt(pageSizeRaw, 10);

  if (
    !Number.isInteger(page) ||
    !Number.isInteger(pageSize) ||
    page < 1 ||
    pageSize < 1 ||
    pageSize > maxPageSize
  ) {
    throw new ApiError({
      code: "INVALID_PAGINATION",
      message: "Invalid page or pageSize query parameter.",
      statusCode: 400,
      details: { page: pageRaw, pageSize: pageSizeRaw, maxPageSize },
    });
  }

  return {
    page,
    pageSize,
    offset: (page - 1) * pageSize,
  };
}

export function buildPaginatedResult<T>(
  items: T[],
  total: number,
  params: Pick<PaginationParams, "page" | "pageSize">,
): PaginatedResult<T> {
  return {
    items,
    page: params.page,
    pageSize: params.pageSize,
    total,
    totalPages: totalPages(total, params.pageSize),
  };
}

export interface SortSpec {
  column: string;
  direction: "ASC" | "DESC";
}

export function parseSort(
  sort: string | undefined,
  allowed: Record<string, string>,
  defaultField: string,
): SortSpec {
  const fallback = allowed[defaultField];
  if (!fallback) {
    throw new Error(`Default sort field ${defaultField} is not allowed`);
  }

  if (!sort?.trim()) {
    return { column: fallback, direction: "ASC" };
  }

  const [field, directionRaw] = sort.split(":");
  const column = allowed[field ?? ""];
  if (!column) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: `Unsupported sort field: ${field ?? sort}`,
      statusCode: 400,
      details: { sort, allowed: Object.keys(allowed) },
    });
  }

  const direction = directionRaw?.toLowerCase() === "desc" ? "DESC" : "ASC";
  if (directionRaw && directionRaw !== "asc" && directionRaw !== "desc") {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "Sort direction must be asc or desc.",
      statusCode: 400,
      details: { sort },
    });
  }

  return { column, direction };
}
