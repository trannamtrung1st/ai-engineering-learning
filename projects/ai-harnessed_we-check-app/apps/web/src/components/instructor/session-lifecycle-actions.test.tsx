import { SessionStatus } from "@wecheck/domain";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { SessionLifecycleActions } from "@/components/instructor/session-lifecycle-actions";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/sessions-api", () => ({
  openSession: vi.fn(),
  closeSession: vi.fn(),
  cancelSession: vi.fn(),
}));

import { openSession, closeSession, cancelSession } from "@/lib/sessions-api";
import type { SessionDetail } from "@/lib/sessions-api";

const baseSession = {
  id: "30000000-0000-4000-8000-000000000302",
  instructorId: "inst",
  classId: "class-1",
  subjectId: "sub-1",
  classCode: "HESD-02",
  className: "HESD Cohort B",
  subjectCode: "SWE-101",
  subjectName: "Software Engineering 101",
  title: "DB-201 — Buổi 3",
  roomName: "Phòng B102",
  roomLatitude: 10.762622 as number | null,
  roomLongitude: 106.660172 as number | null,
  gpsRadiusMeters: 100,
  scheduledStart: "2026-06-30T08:00:00.000Z",
  openedAt: null as string | null,
  closedAt: null as string | null,
};

function renderActions(session: SessionDetail, onSessionUpdated = vi.fn()) {
  return render(
    <MemoryRouter>
      <SessionLifecycleActions session={session} onSessionUpdated={onSessionUpdated} />
    </MemoryRouter>,
  );
}

/** FR-05 / AC-05 / BR-07 — session lifecycle actions */
describe("SessionLifecycleActions (FR-05, AC-05, BR-07)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("TC-FR-04-017: disables Mở buổi học when GPS missing with alert", () => {
    renderActions({
      ...baseSession,
      status: SessionStatus.Draft,
      roomLatitude: null,
      roomLongitude: null,
    });

    expect(screen.getByTestId("session-open-button")).toBeDisabled();
    expect(screen.getByTestId("gps-required-alert")).toHaveTextContent(
      "Vui lòng cấu hình tọa độ phòng học trước khi mở buổi học",
    );
  });

  it("TC-AC-05-001: opens Draft session via confirm dialog", async () => {
    const onUpdated = vi.fn();
    vi.mocked(openSession).mockResolvedValue({
      ok: true,
      data: {
        ...baseSession,
        status: SessionStatus.Active,
        openedAt: "2026-06-29T09:00:00.000Z",
      },
    });

    renderActions({ ...baseSession, status: SessionStatus.Draft }, onUpdated);

    fireEvent.click(screen.getByTestId("session-open-button"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("confirm-dialog-accept"));

    await waitFor(() => {
      expect(openSession).toHaveBeenCalledWith(baseSession.id);
    });
    expect(onUpdated).toHaveBeenCalledWith(
      expect.objectContaining({ status: SessionStatus.Active }),
    );
  });

  it("TC-FR-04-018: cancels Draft session from confirm dialog", async () => {
    const onUpdated = vi.fn();
    vi.mocked(cancelSession).mockResolvedValue({
      ok: true,
      data: {
        ...baseSession,
        status: SessionStatus.Cancelled,
      },
    });

    renderActions({ ...baseSession, status: SessionStatus.Draft }, onUpdated);

    fireEvent.click(screen.getByTestId("session-cancel-button"));
    fireEvent.click(screen.getByTestId("confirm-dialog-accept"));

    await waitFor(() => {
      expect(cancelSession).toHaveBeenCalledWith(baseSession.id);
    });
    expect(onUpdated).toHaveBeenCalledWith(
      expect.objectContaining({ status: SessionStatus.Cancelled }),
    );
  });

  it("TC-AC-05-005: closes Active session via confirm dialog", async () => {
    const onUpdated = vi.fn();
    vi.mocked(closeSession).mockResolvedValue({
      ok: true,
      data: {
        ...baseSession,
        status: SessionStatus.Closed,
        openedAt: "2026-06-29T08:00:00.000Z",
        closedAt: "2026-06-29T09:00:00.000Z",
      },
    });

    renderActions(
      {
        ...baseSession,
        status: SessionStatus.Active,
        openedAt: "2026-06-29T08:00:00.000Z",
      },
      onUpdated,
    );

    fireEvent.click(screen.getByTestId("session-close-button"));
    fireEvent.click(screen.getByTestId("confirm-dialog-accept"));

    await waitFor(() => {
      expect(closeSession).toHaveBeenCalledWith(baseSession.id);
    });
    expect(onUpdated).toHaveBeenCalledWith(
      expect.objectContaining({ status: SessionStatus.Closed }),
    );
  });
});
