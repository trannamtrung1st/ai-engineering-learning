import { SessionStatus } from "@wecheck/domain";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QrFullscreenPresentation } from "@/components/instructor/qr-fullscreen-presentation";
import { appCopy } from "@/lib/copy/status-labels";

vi.mock("@/hooks/use-qr-display-cycle", () => ({
  useQrDisplayCycle: vi.fn(),
}));

vi.mock("@/hooks/use-session-detail", () => ({
  useSessionDetail: vi.fn(),
}));

vi.mock("@/lib/qr-encode", () => ({
  encodeQrDataUrl: vi.fn().mockResolvedValue("data:image/png;base64,qr"),
  QR_PREVIEW_SIZE: 280,
  QR_FULLSCREEN_SIZE: 512,
}));

import { useQrDisplayCycle } from "@/hooks/use-qr-display-cycle";
import { useSessionDetail } from "@/hooks/use-session-detail";

const mockToken = {
  sessionId: "sess-1",
  tokenId: "token-b",
  qrPayload: "wecheck://check-in?token=token-b&session=sess-1",
  issuedAt: "2026-06-29T10:00:00.000Z",
  expiresAt: "2026-06-29T10:00:30.000Z",
  secondsRemaining: 25,
};

const activeSession = {
  id: "sess-1",
  title: "SWE-101 — Buổi 3",
  roomName: "Phòng A101",
  classCode: "HESD-01",
  subjectCode: "SWE-101",
  status: SessionStatus.Active,
};

/** AC-06 / FR-06 / NFR-06 / NFR-20 — fullscreen QR presenter */
describe("QrFullscreenPresentation (AC-06, FR-06, NFR-06, NFR-20)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useSessionDetail).mockReturnValue({
      data: activeSession,
    } as unknown as ReturnType<typeof useSessionDetail>);
    vi.mocked(useQrDisplayCycle).mockReturnValue({
      qrQuery: { isError: false, refetch: vi.fn() } as unknown as ReturnType<
        typeof useQrDisplayCycle
      >["qrQuery"],
      liveToken: mockToken,
      secondsRemaining: 25,
      tokenKey: 1,
      fading: false,
    });
  });

  it("TC-AC-06-018: renders large QR, countdown, and Vietnamese helper on inverse surface", async () => {
    render(<QrFullscreenPresentation sessionId="sess-1" onExit={vi.fn()} />);

    expect(screen.getByTestId("qr-present-page")).toHaveClass("bg-qr-bg");
    expect(screen.getByText("SWE-101 — Buổi 3")).toBeInTheDocument();
    expect(screen.getByText("Phòng A101")).toBeInTheDocument();
    expect(screen.getByText("Quét mã để điểm danh")).toBeInTheDocument();
    expect(screen.getByTestId("qr-countdown")).toHaveTextContent("Mã mới sau 25 giây");
    expect(screen.getByTestId("qr-countdown")).toHaveClass("font-bold");
    expect(screen.getByTestId("qr-countdown")).toHaveClass("text-qr-accent");

    await waitFor(() => {
      expect(screen.getByTestId("qr-code-image")).toBeInTheDocument();
    });
  });

  it("TC-NFR-20-010: presentation countdown uses warning color at 10 seconds or below", () => {
    vi.mocked(useQrDisplayCycle).mockReturnValue({
      qrQuery: { isError: false, refetch: vi.fn() } as unknown as ReturnType<
        typeof useQrDisplayCycle
      >["qrQuery"],
      liveToken: mockToken,
      secondsRemaining: 9,
      tokenKey: 1,
      fading: false,
    });

    render(<QrFullscreenPresentation sessionId="sess-1" onExit={vi.fn()} />);
    expect(screen.getByTestId("qr-countdown")).toHaveClass("text-qr-warning");
  });

  it("TC-NFR-20-014: closed session shows ended overlay", () => {
    vi.mocked(useSessionDetail).mockReturnValue({
      data: { ...activeSession, status: SessionStatus.Closed },
    } as unknown as ReturnType<typeof useSessionDetail>);

    render(<QrFullscreenPresentation sessionId="sess-1" onExit={vi.fn()} />);
    expect(screen.getByTestId("session-ended-overlay")).toHaveTextContent(
      "Buổi học đã kết thúc",
    );
    expect(screen.queryByTestId("qr-code-image")).not.toBeInTheDocument();
  });

  it("invokes onExit when Thoát toàn màn hình clicked", () => {
    const onExit = vi.fn();
    render(<QrFullscreenPresentation sessionId="sess-1" onExit={onExit} />);

    fireEvent.click(screen.getByTestId("qr-exit-fullscreen"));
    expect(onExit).toHaveBeenCalled();
    expect(screen.getByText(appCopy.exitFullscreen)).toBeInTheDocument();
  });
});
