import { describe, expect, it } from "vitest";
import {
  DEFAULT_AUDIT_LOGS_QUERY,
  auditLogsQueryToSearchParams,
  parseAuditLogsListQuery,
} from "./audit-logs-list-query.js";

/** Traceability: FR-30 FR-32 */
describe("audit-logs-list-query", () => {
  it("defaults to timestamp desc pagination", () => {
    const query = parseAuditLogsListQuery(new URLSearchParams());
    expect(query.sortBy).toBe("timestamp");
    expect(query.sortOrder).toBe("desc");
    expect(query.page).toBe(1);
    expect(query.pageSize).toBe(25);
  });

  it("round-trips filter params for PG-15 toolbar sync", () => {
    const state = {
      ...DEFAULT_AUDIT_LOGS_QUERY,
      actionType: "Export",
      actorUserId: "60000000-0000-4000-8000-000000000001",
      from: "2026-01-01",
      to: "2026-06-30",
      page: 2,
    };
    const parsed = parseAuditLogsListQuery(auditLogsQueryToSearchParams(state));
    expect(parsed.actionType).toBe("Export");
    expect(parsed.actorUserId).toBe(state.actorUserId);
    expect(parsed.from).toBe("2026-01-01");
    expect(parsed.page).toBe(2);
  });
});
