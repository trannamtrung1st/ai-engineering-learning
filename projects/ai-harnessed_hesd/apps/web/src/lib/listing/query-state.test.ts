import { describe, expect, it } from "vitest";
import {
  buildListingQueryString,
  DEFAULT_LISTING_QUERY,
  parseListingQuery,
} from "./query-state.js";

/** Traceability: FR-37 */
describe("listing query-state — FR-37", () => {
  it("parses PG-03 attendance history query params with date desc default", () => {
    const params = new URLSearchParams(
      "termId=term-1&classSectionId=sec-1&status=Present&page=2&pageSize=25",
    );
    expect(parseListingQuery(params)).toEqual({
      termId: "term-1",
      classSectionId: "sec-1",
      status: "Present",
      sortBy: "date",
      sortOrder: "desc",
      page: 2,
      pageSize: 25,
    });
  });

  it("builds bookmarkable query string for pagination sync", () => {
    const query = buildListingQueryString({
      ...DEFAULT_LISTING_QUERY,
      termId: "term-1",
      classSectionId: "sec-1",
      page: 2,
    });
    expect(query).toContain("termId=term-1");
    expect(query).toContain("classSectionId=sec-1");
    expect(query).toContain("page=2");
    expect(query).toContain("sortBy=date");
    expect(query).toContain("sortOrder=desc");
  });
});
