import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuditLogList } from "./AuditLogList";

const fetchAuditLogs = vi.fn();

vi.mock("../../lib/api/audit-api.js", () => ({
  fetchAuditLogs: (...args: unknown[]) => fetchAuditLogs(...args),
}));

const sampleEntry = {
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
};

/** Traceability: FR-30 FR-32 BR-22 AC-19 AC-16 */
describe("AuditLogList — PG-15", () => {
  beforeEach(() => {
    fetchAuditLogs.mockReset();
  });

  it("renders toolbar, export audit row, and scoped pagination copy", async () => {
    fetchAuditLogs.mockResolvedValue({
      ok: true,
      items: [sampleEntry],
      pagination: { page: 1, pageSize: 25, totalItems: 1, totalPages: 1 },
    });

    render(
      <MemoryRouter initialEntries={["/audit/logs?actionType=Export"]}>
        <AuditLogList readOnly />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("audit-log-list")).toBeInTheDocument();
    expect(screen.getByTestId("table-toolbar")).toBeInTheDocument();
    expect(screen.getByLabelText("Tìm kiếm danh sách")).toBeInTheDocument();
    expect(screen.getByLabelText("Lọc theo loại hành động")).toBeInTheDocument();
    expect(screen.getByTestId("audit-entry-audit-1")).toBeInTheDocument();
    expect(screen.getByText("Hiển thị 1–1 / 1 bản ghi trong phạm vi được cấp")).toBeInTheDocument();
  });

  it("shows no-results state when filters match zero rows", async () => {
    fetchAuditLogs.mockResolvedValue({
      ok: true,
      items: [],
      pagination: { page: 1, pageSize: 25, totalItems: 0, totalPages: 1 },
    });

    render(
      <MemoryRouter initialEntries={["/audit/logs?actionType=manual_update"]}>
        <AuditLogList readOnly />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Không tìm thấy kết quả")).toBeInTheDocument();
    });
  });
});
