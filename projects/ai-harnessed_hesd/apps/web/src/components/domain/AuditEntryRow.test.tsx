import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuditEntryRow } from "./AuditEntryRow";

const exportEntry = {
  id: "audit-export-1",
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
  correlationId: "corr-export",
  occurredAt: "2026-02-01T10:00:00.000Z",
};

const mutationEntry = {
  ...exportEntry,
  id: "audit-mutation-1",
  actionType: "manual_update",
  targetType: "AttendanceRecord",
  oldStatus: "Absent",
  newStatus: "Manual Present",
  reason: "Sai sót điểm danh",
  format: null,
  scopeFilterSummary: null,
  classSessionId: "70000000-0000-4000-8000-000000000001",
  studentUserId: "60000000-0000-4000-8000-000000000002",
};

/** Traceability: FR-29 FR-30 FR-32 BR-22 AC-19 */
describe("AuditEntryRow — DC-12", () => {
  it("renders export scope and format summary read-only", () => {
    render(
      <MemoryRouter>
        <AuditEntryRow entry={exportEntry} readOnly />
      </MemoryRouter>,
    );

    expect(screen.getByText("Export")).toBeInTheDocument();
    expect(screen.getByText(/csv/)).toBeInTheDocument();
  });

  it("expands mutation detail with old/new status and read-only note", () => {
    render(
      <MemoryRouter>
        <AuditEntryRow entry={mutationEntry} readOnly />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getAllByText("Absent → Manual Present").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Sai sót điểm danh")).toBeInTheDocument();
    expect(
      screen.getByText(/Chế độ chỉ đọc — không có thao tác chỉnh sửa hoặc xóa bản ghi audit/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Xem danh sách buổi học" })).toHaveAttribute(
      "href",
      "/audit/sessions/70000000-0000-4000-8000-000000000001/roster",
    );
  });
});
