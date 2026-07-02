import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { StudentAttendanceHistoryPage } from "./StudentAttendanceHistoryPage";

vi.mock("../../lib/auth/auth-gate.js", () => ({
  isStudentAuthenticated: vi.fn(() => true),
  buildLoginRedirect: vi.fn(() => ({ redirectTo: "/login", message: "Login" })),
}));

vi.mock("../../lib/api/me-api.js", () => ({
  fetchCurrentUser: vi.fn(async () => ({
    ok: true,
    roles: ["Student"],
    classSectionIds: ["50000000-0000-4000-8000-000000000001"],
    displayName: "Student",
  })),
}));

vi.mock("../../components/domain/AttendanceHistoryList.js", () => ({
  AttendanceHistoryList: () => <div data-testid="history-list-stub">History</div>,
}));

/** Traceability: FR-37 AC-16 */
describe("StudentAttendanceHistoryPage — FR-37", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders PG-03 personal history shell without export affordance", async () => {
    render(
      <MemoryRouter>
        <StudentAttendanceHistoryPage />
      </MemoryRouter>,
    );

    expect(screen.getByText("Lịch sử điểm danh")).toBeInTheDocument();
    expect(screen.getByText(/Không có chức năng xuất báo cáo/)).toBeInTheDocument();
    expect(await screen.findByTestId("history-list-stub")).toBeInTheDocument();
  });
});
