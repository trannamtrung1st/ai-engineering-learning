import { AttendanceStatus } from "@wecheck/domain";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { AttendanceHistoryList } from "@/components/student/attendance-history-list";
import type { AttendanceHistoryResponse } from "@/lib/attendance-history-api";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useLocation: () => ({ pathname: "/history", search: "" }),
  };
});

vi.mock("@/lib/attendance-history-api", () => ({
  HISTORY_PAGE_SIZE: 20,
  fetchAttendanceHistory: vi.fn(),
}));

import { fetchAttendanceHistory } from "@/lib/attendance-history-api";

function renderList() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AttendanceHistoryList />
    </QueryClientProvider>,
  );
}

const sampleItem = {
  sessionId: "sess-1",
  sessionDate: "2026-06-29T08:00:00.000Z",
  subject: { id: "sub-1", code: "SWE-101", name: "Kỹ thuật phần mềm" },
  status: AttendanceStatus.Present,
  checkedInAt: "2026-06-29T08:05:00.000Z",
};

const absentItem = {
  sessionId: "sess-2",
  sessionDate: "2026-06-28T08:00:00.000Z",
  subject: { id: "sub-2", code: "DB-201", name: "Cơ sở dữ liệu" },
  status: AttendanceStatus.Absent,
  checkedInAt: null,
};

/** AC-14 / FR-14 — student attendance history list */
describe("AttendanceHistoryList (AC-14, FR-14)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("TC-AC-14-008: shows skeleton while loading", () => {
    vi.mocked(fetchAttendanceHistory).mockReturnValue(new Promise(() => {}));

    renderList();

    expect(screen.getByTestId("history-loading")).toBeInTheDocument();
  });

  it("TC-AC-14-009: shows empty state when no Closed-session records", async () => {
    vi.mocked(fetchAttendanceHistory).mockResolvedValue({
      ok: true,
      data: { items: [], nextCursor: null, totalCount: 0 },
    });

    renderList();

    await waitFor(() => {
      expect(screen.getByTestId("history-empty")).toBeInTheDocument();
    });
    expect(screen.getByText("Chưa có buổi học nào")).toBeInTheDocument();
    expect(screen.queryByTestId("history-load-more")).not.toBeInTheDocument();
  });

  it("TC-AC-14-008: renders card rows with StatusBadge and check-in time for Present", async () => {
    vi.mocked(fetchAttendanceHistory).mockResolvedValue({
      ok: true,
      data: {
        items: [sampleItem, absentItem],
        nextCursor: null,
        totalCount: 2,
      } satisfies AttendanceHistoryResponse,
    });

    renderList();

    await waitFor(() => {
      expect(screen.getByTestId("attendance-history-list")).toBeInTheDocument();
    });

    expect(screen.getByText("Kỹ thuật phần mềm")).toBeInTheDocument();
    expect(screen.getByTestId("status-badge-Present")).toBeInTheDocument();
    expect(screen.getByText(/Điểm danh lúc/)).toBeInTheDocument();
    expect(screen.getByTestId("status-badge-Absent")).toBeInTheDocument();
    expect(screen.queryAllByText(/Điểm danh lúc/)).toHaveLength(1);
    expect(screen.getByTestId("history-end")).toHaveTextContent("Đã hiển thị tất cả");
  });

  it("TC-AC-14-008: load more appends next page without duplicating rows", async () => {
    const page2Item = {
      sessionId: "sess-3",
      sessionDate: "2026-06-27T08:00:00.000Z",
      subject: { id: "sub-3", code: "NET-301", name: "Mạng máy tính" },
      status: AttendanceStatus.Excused,
      checkedInAt: null,
    };

    vi.mocked(fetchAttendanceHistory)
      .mockResolvedValueOnce({
        ok: true,
        data: {
          items: [sampleItem],
          nextCursor: "cursor-page-2",
          totalCount: 2,
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: {
          items: [page2Item],
          nextCursor: null,
          totalCount: 2,
        },
      });

    renderList();

    await waitFor(() => {
      expect(screen.getByTestId(`history-row-${sampleItem.sessionId}`)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Tải thêm" }));

    await waitFor(() => {
      expect(screen.getByTestId(`history-row-${page2Item.sessionId}`)).toBeInTheDocument();
    });

    expect(screen.getAllByTestId(/^history-row-/)).toHaveLength(2);
    expect(fetchAttendanceHistory).toHaveBeenLastCalledWith({
      cursor: "cursor-page-2",
      limit: 20,
    });
  });

  it("TC-AC-14-003: shows retry alert on fetch failure", async () => {
    vi.mocked(fetchAttendanceHistory).mockResolvedValue({
      ok: false,
      status: 500,
      error: { errorCode: "InternalError", message: "Server error" },
    });

    renderList();

    await waitFor(() => {
      expect(screen.getByTestId("history-error-InternalError")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
  });

  it("TC-AC-14-013: redirects to login on 401 Unauthenticated", async () => {
    vi.mocked(fetchAttendanceHistory).mockResolvedValue({
      ok: false,
      status: 401,
      error: { errorCode: "Unauthenticated", message: "Vui lòng đăng nhập để tiếp tục" },
    });

    renderList();

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/login?returnUrl=%2Fhistory", {
        replace: true,
      });
    });
  });
});
