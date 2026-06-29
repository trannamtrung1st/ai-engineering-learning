import { AttendanceStatus } from "@wecheck/domain";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useSessionMonitorPoll } from "@/hooks/use-session-monitor-poll";
import type { SessionMonitorData } from "@/lib/session-monitor-api";

vi.mock("@/lib/session-monitor-api", () => ({
  fetchSessionMonitor: vi.fn(),
}));

import { fetchSessionMonitor } from "@/lib/session-monitor-api";

const closedMonitorData: SessionMonitorData = {
  summary: {
    enrolled: 2,
    present: 1,
    pending: 0,
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
      status: AttendanceStatus.Absent,
      checkedInAt: null,
    },
  ],
  alerts: { codeSharing: false },
};

function renderPollHook(sessionId: string | undefined, pollingEnabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderHook(() => useSessionMonitorPoll(sessionId, pollingEnabled), {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

/** AC-05 / FR-05 — closed-session monitor still loads finalized roster */
describe("useSessionMonitorPoll (AC-05, FR-05, TC-AC-05-020)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("TC-AC-05-020: fetches monitor data when pollingEnabled is false (Closed session)", async () => {
    vi.mocked(fetchSessionMonitor).mockResolvedValue(closedMonitorData);

    const { result } = renderPollHook("30000000-0000-4000-8000-000000000303", false);

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true);
    });

    expect(fetchSessionMonitor).toHaveBeenCalledWith(
      "30000000-0000-4000-8000-000000000303",
    );
    expect(result.current.data?.records.some((r) => r.status === AttendanceStatus.Absent)).toBe(
      true,
    );
  });

  it("does not fetch when sessionId is undefined", () => {
    renderPollHook(undefined, false);
    expect(fetchSessionMonitor).not.toHaveBeenCalled();
  });
});
