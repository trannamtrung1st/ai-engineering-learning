import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LiveRosterPanel } from "./LiveRosterPanel";

vi.mock("../../lib/api/roster-api.js", () => ({
  fetchSessionRoster: vi.fn(),
  subscribeSessionRosterEvents: vi.fn(() => () => undefined),
}));

import { fetchSessionRoster } from "../../lib/api/roster-api";

/** Traceability: FR-19 FR-20 AC-13 */
describe("LiveRosterPanel — FR-19", () => {
  beforeEach(() => {
    vi.mocked(fetchSessionRoster).mockResolvedValue({
      ok: true,
      roster: {
        classSessionId: "70000000-0000-4000-8000-000000000002",
        state: "Open",
        counts: {
          present: 1,
          late: 0,
          pending: 2,
          absent: 0,
          excused: 0,
          manualPresent: 0,
          rejectedAttempts: 1,
        },
        rows: [
          {
            studentUserId: "60000000-0000-4000-8000-000000000002",
            studentCode: "SV001",
            displayName: "Trần Thị Sinh Viên",
            attendanceStatus: "Present",
            checkInMethod: "QR",
            checkInAt: "2026-07-02T08:05:00Z",
            latestAttemptOutcome: "Success",
          },
        ],
      },
    });
  });

  it("TC-FR-19-012: renders summary chips and roster table", async () => {
    render(
      <MemoryRouter>
        <LiveRosterPanel sessionId="70000000-0000-4000-8000-000000000002" sectionCode="SE101-01" />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("live-roster-panel")).toBeInTheDocument();
    expect(screen.getByLabelText("Tóm tắt điểm danh")).toBeInTheDocument();
    expect(screen.getByText("Lần thử lỗi")).toBeInTheDocument();
    expect(screen.getByText("Trần Thị Sinh Viên")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Điều chỉnh" })).toBeInTheDocument();
  });
});
