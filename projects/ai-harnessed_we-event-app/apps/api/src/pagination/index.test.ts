import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ApiError } from "../errors/api-error.js";
import {
  buildPaginatedResult,
  parsePagination,
  totalPages,
} from "./index.js";

describe("pagination", () => {
  it("parses defaults", () => {
    const params = parsePagination({}, { defaultPageSize: 12 });
    assert.equal(params.page, 1);
    assert.equal(params.pageSize, 12);
    assert.equal(params.offset, 0);
  });

  it("rejects invalid page", () => {
    assert.throws(
      () => parsePagination({ page: "0" }, { defaultPageSize: 12 }),
      (error: unknown) =>
        error instanceof ApiError && error.code === "INVALID_PAGINATION",
    );
  });

  it("rejects pageSize above max", () => {
    assert.throws(
      () =>
        parsePagination({ pageSize: "101" }, { defaultPageSize: 12, maxPageSize: 100 }),
      (error: unknown) =>
        error instanceof ApiError && error.code === "INVALID_PAGINATION",
    );
  });

  it("builds envelope with totalPages", () => {
    const result = buildPaginatedResult(["a", "b"], 28, { page: 2, pageSize: 12 });
    assert.deepEqual(result, {
      items: ["a", "b"],
      page: 2,
      pageSize: 12,
      total: 28,
      totalPages: 3,
    });
  });

  it("returns zero totalPages when total is zero", () => {
    assert.equal(totalPages(0, 12), 0);
  });
});
