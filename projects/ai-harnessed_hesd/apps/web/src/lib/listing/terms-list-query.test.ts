/**
 * Traceability: FR-01
 */
import { describe, expect, it } from "vitest";
import { parseTermsListQuery, termsListQueryToSearchParams } from "./terms-list-query";

describe("terms list query (FR-01)", () => {
  it("round-trips search and pagination params", () => {
    const params = new URLSearchParams("search=2026&page=2&pageSize=10&sortOrder=desc&activeOnly=true");
    const state = parseTermsListQuery(params);
    expect(state.search).toBe("2026");
    expect(state.page).toBe(2);
    expect(state.activeOnly).toBe(true);
    expect(termsListQueryToSearchParams(state).toString()).toContain("search=2026");
  });
});
