import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AttendanceHistoryList } from "./AttendanceHistoryList";

vi.mock("../../lib/api/attendance-history-api.js", () => ({
  fetchAttendanceHistory: vi.fn(async () => ({
    ok: true,
    rows: [
      {
        attendanceRecordId: "rec-1",
        studentUserId: "student-1",
        studentCode: "SV001",
        classSessionId: "sess-1",
        classSectionId: "sec-1",
        sectionCode: "SE101-01",
        attendanceStatus: "Present",
        checkInAt: "2026-02-01T08:05:00.000Z",
        checkInMethod: "QR",
        sessionDate: "2026-02-01T08:00:00.000Z",
      },
    ],
    pagination: { page: 1, pageSize: 25, totalItems: 1, totalPages: 1 },
  })),
  groupRowsBySection: vi.fn((rows) => new Map([["SE101-01", rows]])),
}));

/** Traceability: FR-37 BR-19 */
describe("AttendanceHistoryList — FR-37", () => {
  it("renders self-scoped history with toolbar and no export action", async () => {
    render(
      <MemoryRouter initialEntries={["/me/attendance?termId=term-1"]}>
        <AttendanceHistoryList
          defaultTermId="term-1"
          termOptions={[{ value: "term-1", label: "HK 2026" }]}
          sectionOptions={[{ value: "sec-1", label: "SE101-01" }]}
        />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("attendance-history-list")).toBeInTheDocument();
    expect(screen.getByTestId("table-toolbar")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Xuất CSV" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "SE101-01" })).toBeInTheDocument();
    expect(screen.getByLabelText("Phương thức QR")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});
