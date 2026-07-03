import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildExportFilters,
  createAttendanceExport,
  downloadAttendanceExport,
  fetchAttendanceReport,
} from "./reporting-api.js";

const apiRequest = vi.fn();

vi.mock("./client.js", () => ({
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

vi.mock("./config.js", () => ({
  apiV1BaseUrl: () => "http://api.test/api/v1",
}));

vi.mock("../auth/session.js", () => ({
  getAccessToken: () => "token-1",
}));

/** Traceability: FR-27 FR-28 BR-18 AC-15 AC-17 */
describe("reporting-api — PG-13/PG-14", () => {
  beforeEach(() => {
    apiRequest.mockReset();
    vi.stubGlobal("fetch", vi.fn());
  });

  it("serializes report query params for search, filters, sort, and pagination", async () => {
    apiRequest.mockResolvedValueOnce({
      data: [],
      meta: {
        requestId: "req-1",
        timestamp: "2026-07-02T00:00:00Z",
        pagination: { page: 2, pageSize: 25, totalItems: 0, totalPages: 1 },
      },
      error: null,
    });

    const result = await fetchAttendanceReport({
      termId: "term-1",
      classSectionId: "section-1",
      search: "SV001",
      status: "Absent",
      from: "2026-02-01",
      to: "2026-02-28",
      sortBy: "status",
      sortOrder: "asc",
      page: 2,
      pageSize: 25,
    });

    expect(result.ok).toBe(true);
    const firstCall = apiRequest.mock.calls[0];
    expect(firstCall).toBeDefined();
    const path = firstCall?.[0] as string;
    expect(path).toContain("/reports/attendance?");
    expect(path).toContain("search=SV001");
    expect(path).toContain("status=Absent");
    expect(path).toContain("from=2026-02-01");
    expect(path).toContain("sortBy=status");
    expect(path).toContain("sortOrder=asc");
    expect(path).toContain("page=2");
  });

  it("builds export filters from active toolbar state only", () => {
    expect(
      buildExportFilters({
        termId: "term-1",
        classSectionId: "section-1",
        search: "SV001",
        status: "Late",
        from: "2026-02-01",
        to: undefined,
        sortBy: "date",
        sortOrder: "desc",
        page: 3,
        pageSize: 25,
      }),
    ).toEqual({
      termId: "term-1",
      classSectionId: "section-1",
      search: "SV001",
      status: "Late",
      from: "2026-02-01",
    });
  });

  it("posts CSV export with idempotency and downloads text/csv artifact", async () => {
    apiRequest.mockResolvedValueOnce({
      data: { exportJobId: "job-1", status: "Completed", format: "csv" },
      meta: { requestId: "req-1", timestamp: "2026-07-02T00:00:00Z" },
      error: null,
    });
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response("studentCode\nSV001", {
        status: 200,
        headers: {
          "content-disposition": 'attachment; filename="attendance-export-job-1.csv"',
        },
      }),
    );

    const exportResult = await createAttendanceExport({
      termId: "term-1",
      sortBy: "date",
      sortOrder: "desc",
      page: 1,
      pageSize: 25,
    });
    const downloadResult = await downloadAttendanceExport("job-1");

    expect(exportResult.ok).toBe(true);
    const firstCall = apiRequest.mock.calls[0];
    expect(firstCall).toBeDefined();
    expect(firstCall?.[0]).toBe("/exports/attendance");
    expect(firstCall?.[1]).toMatchObject({
      method: "POST",
      body: { format: "csv", filters: { termId: "term-1" } },
    });
    expect(downloadResult).toEqual({
      ok: true,
      csv: "studentCode\nSV001",
      filename: "attendance-export-job-1.csv",
    });
  });
});
