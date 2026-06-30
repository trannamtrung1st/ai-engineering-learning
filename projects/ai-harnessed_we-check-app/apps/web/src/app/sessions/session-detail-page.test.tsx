import { SessionStatus } from "@wecheck/domain";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { SessionDetailPage } from "@/app/sessions/session-detail-page";

vi.mock("@/hooks/use-session-detail", () => ({
  useSessionDetail: vi.fn(),
}));

import { useSessionDetail } from "@/hooks/use-session-detail";

const activeSession = {
  id: "30000000-0000-4000-8000-000000000301",
  instructorId: "inst",
  classId: "class-1",
  subjectId: "sub-1",
  classCode: "HESD-01",
  className: "HESD Cohort A",
  subjectCode: "SWE-101",
  subjectName: "Software Engineering 101",
  title: "SWE-101 — Buổi 5",
  roomName: "Phòng A201",
  roomLatitude: 10.762622,
  roomLongitude: 106.660172,
  gpsRadiusMeters: 100,
  scheduledStart: "2026-06-30T08:00:00.000Z",
  status: SessionStatus.Active,
  openedAt: "2026-06-29T09:00:00.000Z",
  closedAt: null,
};

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/sessions/sess-1?tab=monitor"]}>
        <Routes>
          <Route path="/sessions/:id" element={<SessionDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** AC-05 / FR-05 — session detail hub lifecycle UI */
describe("SessionDetailPage (AC-05, FR-05)", () => {
  it("TC-AC-05-018: shows Mở lúc openedAt timestamp on Active session detail", () => {
    vi.mocked(useSessionDetail).mockReturnValue({
      data: activeSession,
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useSessionDetail>);

    renderDetail();

    expect(screen.getByTestId("session-opened-at")).toHaveTextContent(/Mở lúc:/);
  });
});
