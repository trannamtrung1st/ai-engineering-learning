/**
 * Traceability: FR-07 FR-10 AC-01
 * TC-FR-07-012
 */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LecturerSessionList } from "./LecturerSessionList";

vi.mock("../../lib/api/session-api", () => ({
  fetchClassSessions: vi.fn(),
  formatRoomLabel: (session: { roomCode: string | null; roomName: string | null }) =>
    session.roomCode ?? "—",
  formatScheduledAt: () => "08:00",
  formatSessionLabel: (session: { courseName: string }) => session.courseName,
}));

import { fetchClassSessions } from "../../lib/api/session-api";

describe("LecturerSessionList (FR-07 FR-10 AC-01)", () => {
  beforeEach(() => {
    vi.mocked(fetchClassSessions).mockResolvedValue({
      ok: true,
      items: [
        {
          classSessionId: "70000000-0000-4000-8000-000000000001",
          classSectionId: "50000000-0000-4000-8000-000000000001",
          sectionCode: "SE101-01",
          courseName: "Nhập môn phần mềm",
          roomCode: "A101",
          roomName: "Phòng A101",
          scheduledStartAt: "2026-07-03T08:00:00Z",
          scheduledEndAt: "2026-07-03T09:30:00Z",
          state: "Scheduled",
          openedAt: null,
          closedAt: null,
        },
      ],
      pagination: { page: 1, pageSize: 25, totalItems: 1, totalPages: 1 },
    });
  });

  it("TC-FR-07-012: renders scheduled session row with open link", async () => {
    render(
      <MemoryRouter initialEntries={["/lecturer/sessions"]}>
        <LecturerSessionList />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("SE101-01")).toBeInTheDocument();
    });

    expect(screen.getByRole("link", { name: "Mở điểm danh" })).toHaveAttribute(
      "href",
      "/lecturer/sessions/70000000-0000-4000-8000-000000000001?action=open",
    );
  });
});
