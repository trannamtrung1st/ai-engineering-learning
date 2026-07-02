/**
 * Traceability: FR-07 AC-01
 * TC-FR-07-012 TC-AC-01-008 TC-FR-14-011
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { SessionControlBar, type SessionControlBarProps } from "./SessionControlBar";

function renderBar(props: SessionControlBarProps) {
  return render(
    <MemoryRouter>
      <SessionControlBar {...props} />
    </MemoryRouter>,
  );
}

describe("SessionControlBar (FR-07 AC-01)", () => {
  it("TC-AC-01-008: shows open action for Scheduled and openedAt for Open state", () => {
    const { rerender } = renderBar({
      sectionCode: "SE101-01",
      roomName: "A101 · Phòng A101",
      scheduledAt: "Thứ 3 · 08:00",
      sessionState: "Scheduled",
      onOpen: vi.fn(),
    });

    expect(screen.getByRole("button", { name: "Mở điểm danh" })).toBeInTheDocument();
    expect(screen.getByTestId("session-control-context")).toHaveTextContent("A101");
    expect(screen.getByTestId("session-control-context")).toHaveTextContent("Thứ");

    rerender(
      <MemoryRouter>
        <SessionControlBar
          sectionCode="SE101-01"
          roomName="A101 · Phòng A101"
          scheduledAt="Thứ 3 · 08:00"
          sessionState="Open"
          sessionId="70000000-0000-4000-8000-000000000002"
          openedAt="2026-07-02T08:00:00Z"
          onClose={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("session-opened-at")).toHaveTextContent("Lúc mở");
    expect(screen.getByRole("button", { name: "Đóng điểm danh" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Xem danh sách" })).toHaveAttribute(
      "href",
      "/lecturer/sessions/70000000-0000-4000-8000-000000000002/roster",
    );
  });

  it("invokes open handler from Scheduled state", () => {
    const onOpen = vi.fn();
    renderBar({
      sectionCode: "SE101-01",
      roomName: "A101 · Phòng A101",
      scheduledAt: "Thứ 3 · 08:00",
      sessionState: "Scheduled",
      onOpen,
    });

    fireEvent.click(screen.getByRole("button", { name: "Mở điểm danh" }));
    expect(onOpen).toHaveBeenCalledOnce();
  });
});
