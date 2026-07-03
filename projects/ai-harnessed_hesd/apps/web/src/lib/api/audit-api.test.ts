import { describe, expect, it, vi, beforeEach } from "vitest";
import { fetchAuditLogs } from "./audit-api.js";

vi.mock("./client.js", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "./client.js";

/** Traceability: FR-30 FR-32 BR-22 AC-19 */
describe("audit-api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("returns paginated audit entries from GET /audit-logs", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      data: [
        {
          id: "audit-1",
          actionType: "Export",
          actorUserId: "60000000-0000-4000-8000-000000000001",
          actorRole: "Lecturer",
          actorDisplayName: "Nguyễn Văn Giảng",
          targetType: "ExportJob",
          targetId: "80000000-0000-4000-8000-000000000099",
          studentUserId: null,
          classSessionId: null,
          classSectionId: "50000000-0000-4000-8000-000000000001",
          oldStatus: null,
          newStatus: null,
          outcome: null,
          reason: null,
          scopeFilterSummary: "classSectionId=50000000-0000-4000-8000-000000000001",
          format: "csv",
          correlationId: "corr-1",
          occurredAt: "2026-02-01T10:00:00.000Z",
        },
      ],
      meta: {
        requestId: "req-1",
        timestamp: "2026-02-01T10:00:00.000Z",
        pagination: { page: 1, pageSize: 25, totalItems: 1, totalPages: 1 },
      },
      error: null,
    } as Awaited<ReturnType<typeof apiRequest>>);

    const result = await fetchAuditLogs({
      actionType: "Export",
      sortBy: "timestamp",
      sortOrder: "desc",
      page: 1,
      pageSize: 25,
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.items[0]?.format).toBe("csv");
      expect(result.items[0]?.scopeFilterSummary).toContain("classSectionId");
    }
  });
});
