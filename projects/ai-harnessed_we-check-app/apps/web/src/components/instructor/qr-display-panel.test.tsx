import { SessionStatus } from "@wecheck/domain";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QrDisplayPanel } from "@/components/instructor/qr-display-panel";

vi.mock("@/hooks/use-qr-display-cycle", () => ({
  useQrDisplayCycle: vi.fn(),
}));

vi.mock("@/lib/qr-encode", () => ({
  encodeQrDataUrl: vi.fn().mockResolvedValue("data:image/png;base64,qr"),
  QR_PREVIEW_SIZE: 280,
  QR_FULLSCREEN_SIZE: 512,
}));

import { useQrDisplayCycle } from "@/hooks/use-qr-display-cycle";

const mockToken = {
  sessionId: "sess-1",
  tokenId: "token-a",
  qrPayload: "wecheck://check-in?token=token-a&session=sess-1",
  issuedAt: "2026-06-29T10:00:00.000Z",
  expiresAt: "2026-06-29T10:00:30.000Z",
  secondsRemaining: 28,
};

function renderPanel(status: SessionStatus = SessionStatus.Active) {
  return render(
    <MemoryRouter>
      <QrDisplayPanel
        sessionId="sess-1"
        sessionStatus={status}
        classCode="HESD-01"
        subjectCode="SWE-101"
        roomName="Phòng A101"
      />
    </MemoryRouter>,
  );
}

/** AC-06 / FR-06 / NFR-06 / NFR-20 — instructor QR tab display */
describe("QrDisplayPanel (AC-06, FR-06, NFR-06, NFR-20)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useQrDisplayCycle).mockReturnValue({
      qrQuery: {
        isError: false,
        refetch: vi.fn(),
      } as unknown as ReturnType<typeof useQrDisplayCycle>["qrQuery"],
      liveToken: mockToken,
      secondsRemaining: 28,
      tokenKey: 1,
      fading: false,
    });
  });

  it("TC-AC-06-017: renders scannable QR, countdown, and Trình chiếu QR link for Active session", async () => {
    renderPanel();

    expect(screen.getByTestId("qr-display-panel")).toBeInTheDocument();
    expect(screen.getByTestId("qr-session-meta")).toHaveTextContent(
      "HESD-01 · SWE-101 · Phòng A101",
    );
    expect(screen.getByTestId("qr-countdown")).toHaveTextContent("Mã mới sau 28 giây");
    expect(screen.getByTestId("qr-present-link")).toHaveAttribute(
      "href",
      "/sessions/sess-1/qr-present",
    );

    await waitFor(() => {
      expect(screen.getByTestId("qr-code-image")).toBeInTheDocument();
    });
    expect(screen.getByTestId("qr-code-image")).toHaveAttribute(
      "data-token-id",
      "token-a",
    );
  });

  it("TC-AC-06-019: Draft session shows Buổi học chưa mở without QR image", () => {
    renderPanel(SessionStatus.Draft);

    expect(screen.getByTestId("session-not-active")).toHaveTextContent("Buổi học chưa mở");
    expect(screen.queryByTestId("qr-code-image")).not.toBeInTheDocument();
    expect(useQrDisplayCycle).toHaveBeenCalledWith("sess-1", false);
  });

  it("TC-AC-06-019: Closed session shows ended messaging without QR image", () => {
    renderPanel(SessionStatus.Closed);

    expect(screen.getByTestId("session-not-active")).toHaveTextContent(
      "Buổi học đã kết thúc",
    );
    expect(screen.queryByTestId("qr-code-image")).not.toBeInTheDocument();
  });

  it("TC-NFR-06-015: countdown uses warning accent at 10 seconds or below", () => {
    vi.mocked(useQrDisplayCycle).mockReturnValue({
      qrQuery: { isError: false, refetch: vi.fn() } as unknown as ReturnType<
        typeof useQrDisplayCycle
      >["qrQuery"],
      liveToken: mockToken,
      secondsRemaining: 10,
      tokenKey: 1,
      fading: false,
    });

    renderPanel();
    expect(screen.getByTestId("qr-countdown")).toHaveClass("text-qr-warning");
  });

  it("shows retry when QR poll fails", () => {
    const refetch = vi.fn();
    vi.mocked(useQrDisplayCycle).mockReturnValue({
      qrQuery: { isError: true, refetch } as unknown as ReturnType<
        typeof useQrDisplayCycle
      >["qrQuery"],
      liveToken: undefined,
      secondsRemaining: 30,
      tokenKey: 0,
      fading: false,
    });

    renderPanel();
    expect(screen.getByTestId("qr-display-error")).toBeInTheDocument();
    screen.getByRole("button", { name: "Thử lại" }).click();
    expect(refetch).toHaveBeenCalled();
  });
});
