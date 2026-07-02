import { describe, expect, it } from "vitest";
import {
  DEFAULT_SESSION_LIST_QUERY,
  parseSessionListQuery,
  sessionListQueryToSearchParams,
} from "./session-list-query";

describe("session-list-query (PG-04 FR-10)", () => {
  it("parses URL params for lecturer session listing", () => {
    const params = new URLSearchParams(
      "classSectionId=sec-1&state=Open&search=SE101&page=2&sortBy=state&sortOrder=asc",
    );
    const query = parseSessionListQuery(params);
    expect(query.classSectionId).toBe("sec-1");
    expect(query.state).toBe("Open");
    expect(query.search).toBe("SE101");
    expect(query.page).toBe(2);
    expect(query.sortBy).toBe("state");
    expect(query.sortOrder).toBe("asc");
  });

  it("round-trips default listing query", () => {
    const params = sessionListQueryToSearchParams(DEFAULT_SESSION_LIST_QUERY);
    expect(params.get("sortBy")).toBe("startTime");
    expect(params.get("page")).toBe("1");
  });
});
