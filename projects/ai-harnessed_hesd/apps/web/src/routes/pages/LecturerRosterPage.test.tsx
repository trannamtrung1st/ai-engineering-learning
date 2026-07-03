import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LecturerRosterPage } from "./LecturerRosterPage";

vi.mock("../../lib/auth/staff-gate.js", () => ({
  isStaffAuthenticated: vi.fn(() => true),
  buildStaffLoginRedirect: vi.fn(() => "/login"),
}));

vi.mock("../../lib/api/session-api.js", () => ({
  fetchClassSessionById: vi.fn(),
  formatSessionLabel: vi.fn(() => "Nhập môn phần mềm"),
}));

vi.mock("../../components/domain/LiveRosterPanel.js", () => ({
  LiveRosterPanel: () => <div data-testid="live-roster-panel-stub">roster</div>,
}));

import { fetchClassSessionById } from "../../lib/api/session-api";

/** Traceability: FR-19 */
describe("LecturerRosterPage — FR-19 PG-06", () => {
  beforeEach(() => {
    vi.mocked(fetchClassSessionById).mockResolvedValue({
      ok: true,
      session: {
        classSessionId: "70000000-0000-4000-8000-000000000002",
        classSectionId: "50000000-0000-4000-8000-000000000001",
        sectionCode: "SE101-01",
        courseName: "Nhập môn phần mềm",
        roomCode: "A101",
        roomName: "Phòng A101",
        scheduledStartAt: "2026-07-02T08:00:00Z",
        scheduledEndAt: "2026-07-02T09:30:00Z",
        state: "Open",
        openedAt: "2026-07-02T08:00:00Z",
        closedAt: null,
      },
    });
  });

  it("renders PG-06 live roster route with session context", async () => {
    render(
      <MemoryRouter initialEntries={["/lecturer/sessions/70000000-0000-4000-8000-000000000002/roster"]}>
        <Routes>
          <Route path="/lecturer/sessions/:sessionId/roster" element={<LecturerRosterPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("live-roster-panel-stub")).toBeInTheDocument();
    expect(screen.getByText("Danh sách điểm danh trực tiếp")).toBeInTheDocument();
  });
});
