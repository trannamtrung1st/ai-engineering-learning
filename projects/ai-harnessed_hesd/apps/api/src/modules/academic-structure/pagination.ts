import type { PaginationMeta } from "./types.js";

export function parsePagination(query: {
  page?: string;
  pageSize?: string;
}): { page: number; pageSize: number; offset: number } {
  const page = Math.max(1, Number.parseInt(query.page ?? "1", 10) || 1);
  const rawSize = Number.parseInt(query.pageSize ?? "25", 10) || 25;
  const pageSize = Math.min(100, Math.max(1, rawSize));
  return { page, pageSize, offset: (page - 1) * pageSize };
}

export function buildPaginationMeta(
  page: number,
  pageSize: number,
  totalItems: number,
): PaginationMeta {
  const totalPages = totalItems === 0 ? 0 : Math.ceil(totalItems / pageSize);
  return { page, pageSize, totalItems, totalPages };
}
