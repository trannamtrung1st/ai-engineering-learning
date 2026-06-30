import { AttendanceStatus } from "@wecheck/domain";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SessionMonitorDashboard } from "@/components/domain/session/session-monitor-dashboard";
import type { SessionMonitorData } from "@/lib/session-monitor-api";
import { MONITOR_POLL_MS } from "@/hooks/use-session-monitor-poll";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
  },
}));

vi.mock("@/hooks/use-session-monitor-poll", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-session-monitor-poll")>();
  return {
    ...actual,
    useSessionMonitorPoll: vi.fn(),
  };
});

import { useSessionMonitorPoll } from "@/hooks/use-session-monitor-poll";
import { toast } from "sonner";

const sampleData: SessionMonitorData = {
  summary: {
    enrolled: 4,
    present: 1,
    pending: 2,
    absent: 1,
    excused: 0,
    rejected: 0,
  },
  records: [
    {
      id: "r1",
      studentId: "s1",
      institutionalId: "SV2026001",
      displayName: "Nguyễn Văn A",
      status: AttendanceStatus.Present,
      checkedInAt: "2026-06-29T08:05:00.000Z",
    },
    {
      id: "r2",
      studentId: "s2",
      institutionalId: "SV2026002",
      displayName: "Trần Thị B",
      status: AttendanceStatus.Pending,
      checkedInAt: null,
    },
    {
      id: "r3",
      studentId: "s3",
      institutionalId: "SV2026003",
      displayName: "Lê Văn C",
      status: AttendanceStatus.Absent,
      checkedInAt: null,
    },
    {
      id: "r4",
      studentId: "s4",
      institutionalId: "SV2026004",
      displayName: "Phạm Thị D",
      status: AttendanceStatus.Excused,
      checkedInAt: null,
    },
  ],
  alerts: { codeSharing: false },
};

function mockPoll(overrides: Partial<ReturnType<typeof useSessionMonitorPoll>> = {}) {
  vi.mocked(useSessionMonitorPoll).mockReturnValue({
    data: sampleData,
    isLoading: false,
    isError: false,
    dataUpdatedAt: Date.parse("2026-06-29T10:00:05.000Z"),
    refetch: vi.fn(),
    ...overrides,
  } as ReturnType<typeof useSessionMonitorPoll>);
}

function renderDashboard(props: { sessionId?: string; pollingEnabled?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SessionMonitorDashboard sessionId="sess-1" pollingEnabled {...props} />
    </QueryClientProvider>,
  );
}

/** AC-15 / FR-15 / NFR-08 — instructor live session monitor */
describe("SessionMonitorDashboard (AC-15, FR-15, NFR-08)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    mockPoll();
  });

  it("TC-AC-15-006: renders Đã điểm danh / Chưa điểm danh / Vắng StatCards from API summary", () => {
    renderDashboard();

    expect(screen.getByTestId("stat-card-present")).toHaveTextContent("1");
    expect(screen.getByTestId("stat-card-present")).toHaveTextContent("/ 4");
    expect(screen.getByTestId("stat-card-pending")).toHaveTextContent("2");
    expect(screen.getByTestId("stat-card-absent")).toHaveTextContent("1");
    expect(screen.getByTestId("monitor-live-summary")).toHaveTextContent(
      "Đã điểm danh 1 trên 4",
    );
  });

  it("TC-NFR-08-009: poll hook uses 5 second interval when polling enabled", () => {
    renderDashboard();
    expect(useSessionMonitorPoll).toHaveBeenCalledWith("sess-1", true);
    expect(MONITOR_POLL_MS).toBe(5_000);
  });

  it("TC-NFR-08-014: polling disabled when pollingEnabled is false", () => {
    renderDashboard({ pollingEnabled: false });
    expect(useSessionMonitorPoll).toHaveBeenCalledWith("sess-1", false);
  });

  it("TC-AC-15-006: shows poll status timestamp after successful fetch", () => {
    renderDashboard();
    expect(screen.getByTestId("monitor-poll-status")).toHaveTextContent(/Cập nhật lúc/);
  });

  it("TC-NFR-08-013: shows retry when poll fails and surfaces toast", () => {
    mockPoll({ isError: true, data: undefined });
    renderDashboard();

    expect(screen.getByTestId("monitor-poll-status")).toHaveTextContent(
      "Không thể cập nhật — thử lại",
    );
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
    expect(toast.error).toHaveBeenCalled();
  });

  it("TC-AC-15-007: sorts roster by Trạng thái ascending (Chờ → Vắng → Có mặt → Có phép)", async () => {
    renderDashboard();

    fireEvent.click(screen.getByTestId("monitor-sort-status"));

    await waitFor(() => {
      expect(screen.getByTestId("monitor-sort-status")).toHaveAttribute(
        "aria-sort",
        "ascending",
      );
    });

    const rows = screen.getAllByRole("row").slice(1);
    const statuses = rows.map((row) => row.querySelector("[data-testid^='status-badge-']")?.getAttribute("data-testid"));
    expect(statuses).toEqual([
      "status-badge-Pending",
      "status-badge-Absent",
      "status-badge-Present",
      "status-badge-Excused",
    ]);
  });

  it("TC-AC-15-013: status filter shows only Present rows while StatCards keep full totals", () => {
    renderDashboard();

    fireEvent.change(screen.getByTestId("monitor-status-filter"), {
      target: { value: AttendanceStatus.Present },
    });

    expect(screen.getByTestId("monitor-row-sv2026001")).toBeInTheDocument();
    expect(screen.queryByTestId("monitor-row-sv2026002")).not.toBeInTheDocument();
    expect(screen.getByTestId("stat-card-present")).toHaveTextContent("1");
    expect(screen.getByTestId("stat-card-pending")).toHaveTextContent("2");
  });

  it("TC-AC-15-003: roster rows show StatusBadge and check-in timestamp for Present", () => {
    renderDashboard();

    expect(screen.getByTestId("status-badge-Present")).toBeInTheDocument();
    expect(screen.getByTestId("monitor-row-sv2026001")).toHaveTextContent(/8:05/);
  });

  it("TC-AC-15-006: spoof preview fixture renders SpoofAlertBadge when showSpoofAlert", () => {
    mockPoll({ data: undefined });
    render(
      <SessionMonitorDashboard showSpoofAlert />,
    );
    expect(screen.getByTestId("spoof-alert-badge")).toBeInTheDocument();
  });
});
