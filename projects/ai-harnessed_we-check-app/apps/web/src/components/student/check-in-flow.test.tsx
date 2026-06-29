import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { CheckInFlow } from "@/components/student/check-in-flow";
import { CAMERA_CONSENT_KEY, LOCATION_CONSENT_KEY } from "@/lib/checkin-outcome";
import { PREVIEW_TOKEN_IDS } from "@/lib/preview-fixtures";

vi.mock("@/lib/auth-session", () => ({
  fetchAuthUser: vi.fn().mockResolvedValue({
    ok: true,
    user: { id: "1", role: "Student" },
  }),
}));

vi.mock("@/lib/geolocation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/geolocation")>();
  return {
    ...actual,
    captureGeolocation: vi.fn(),
  };
});

vi.mock("@/lib/check-in-api", () => ({
  submitCheckInWithRetry: vi.fn(),
}));

vi.mock("@/lib/preview-sim", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/preview-sim")>();
  return {
    ...actual,
    readMockLocationDetected: vi.fn(() => false),
    readExpireSessionOnSubmit: vi.fn(() => false),
  };
});

vi.mock("@/lib/session-monitor-api", () => ({
  previewExpireSession: vi.fn().mockResolvedValue(undefined),
}));

import { fetchAuthUser } from "@/lib/auth-session";
import { captureGeolocation } from "@/lib/geolocation";
import { submitCheckInWithRetry } from "@/lib/check-in-api";
import { readExpireSessionOnSubmit, readMockLocationDetected } from "@/lib/preview-sim";
import { previewExpireSession } from "@/lib/session-monitor-api";

/** AC-02, AC-07, AC-08, AC-09, AC-10, FR-07, FR-08, NFR-18, NFR-19 */
describe("CheckInFlow (AC-07, AC-08, FR-07, FR-08, NFR-18, NFR-19)", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, search: "" },
    });
    localStorage.setItem(LOCATION_CONSENT_KEY, "1");
    localStorage.setItem(CAMERA_CONSENT_KEY, "1");
    vi.mocked(fetchAuthUser).mockResolvedValue({
      ok: true,
      user: {
        id: "1",
        institutionalId: "SV2026001",
        displayName: "Student One",
        email: "student@example.edu.vn",
        role: "Student" as const,
      },
    });
    vi.mocked(captureGeolocation).mockResolvedValue({
      ok: true,
      position: { latitude: 10.7627, longitude: 106.6602, accuracyMeters: 12 },
    });
    vi.mocked(submitCheckInWithRetry).mockResolvedValue({ outcome: "Present" });
  });

  afterEach(() => {
    localStorage.removeItem(LOCATION_CONSENT_KEY);
    localStorage.removeItem(CAMERA_CONSENT_KEY);
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
    vi.clearAllMocks();
  });

  function setWindowSearch(search: string) {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, search },
    });
  }

  function renderFlow(path = "/check-in") {
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/check-in" element={<CheckInFlow />} />
          <Route path="/history" element={<div data-testid="history-page">Lịch sử</div>} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("shows location consent before first check-in (NFR-12, NFR-19)", () => {
    localStorage.removeItem(LOCATION_CONSENT_KEY);
    renderFlow();
    expect(screen.getByText(/Quyền truy cập vị trí/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Đồng ý" }));
    expect(screen.getByTestId("qr-scanner-view")).toBeInTheDocument();
  });

  it("deep link with token skips scan and submits check-in (AC-02, FR-07, AC-07)", async () => {
    renderFlow(`/check-in?token=${PREVIEW_TOKEN_IDS.stale}`);

    const submit = await screen.findByTestId("check-in-submit");
    expect(submit).toBeDisabled();

    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });

    fireEvent.click(submit);

    await waitFor(() => {
      expect(submitCheckInWithRetry).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-Present")).toBeInTheDocument();
    });
  });

  it("shows ExpiredQr outcome for stale token from API (BR-03, AC-09)", async () => {
    vi.mocked(submitCheckInWithRetry).mockResolvedValue({ outcome: "ExpiredQr" });
    renderFlow(`/check-in?token=stale-token-id`);

    const submit = await screen.findByTestId("check-in-submit");
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-ExpiredQr")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Quét lại" })).toBeInTheDocument();
  });

  it("shows TokenAlreadyUsed for consumed token from API (BR-11, AC-09)", async () => {
    vi.mocked(submitCheckInWithRetry).mockResolvedValue({ outcome: "TokenAlreadyUsed" });
    renderFlow(`/check-in?token=consumed-token-id`);

    const submit = await screen.findByTestId("check-in-submit");
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-TokenAlreadyUsed")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Quét lại" })).toBeInTheDocument();
  });

  it("shows camera consent before scanner on first visit (NFR-19)", () => {
    localStorage.removeItem(CAMERA_CONSENT_KEY);
    renderFlow();
    expect(screen.getByTestId("camera-consent-banner")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Đồng ý" }));
    expect(screen.getByTestId("qr-scanner-view")).toBeInTheDocument();
  });

  it("shows GpsDisabled without API when geolocation denied (AC-08c, BR-12, NFR-19)", async () => {
    vi.mocked(captureGeolocation).mockResolvedValue({ ok: false, reason: "denied" });
    renderFlow(`/check-in?token=${PREVIEW_TOKEN_IDS.stale}`);

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-GpsDisabled")).toBeInTheDocument();
    });
    expect(submitCheckInWithRetry).not.toHaveBeenCalled();
  });

  it("opens GPS permission guide from GpsDisabled CTA (NFR-19)", async () => {
    vi.mocked(captureGeolocation).mockResolvedValue({ ok: false, reason: "denied" });
    renderFlow(`/check-in?token=${PREVIEW_TOKEN_IDS.stale}`);

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-GpsDisabled")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Hướng dẫn cấp quyền" }));
    expect(screen.getByTestId("permission-guide-modal-gps")).toBeInTheDocument();
  });

  it("redirects unauthenticated deep link to login (AC-02)", async () => {
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, href: "" },
    });

    vi.mocked(fetchAuthUser).mockResolvedValue({ ok: false, errorCode: "Unauthenticated" });
    renderFlow(`/check-in?token=${PREVIEW_TOKEN_IDS.stale}`);

    await waitFor(() => {
      expect(window.location.href).toContain("/login?returnUrl=");
    });

    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("navigates to history from DuplicateCheckIn outcome (AC-09, FR-09)", async () => {
    vi.mocked(submitCheckInWithRetry).mockResolvedValue({
      outcome: "DuplicateCheckIn",
      priorCheckedInAt: "2026-06-29T10:30:00.000Z",
    });
    render(
      <MemoryRouter initialEntries={[`/check-in?token=${PREVIEW_TOKEN_IDS.valid}`]}>
        <Routes>
          <Route path="/check-in" element={<CheckInFlow />} />
          <Route path="/history" element={<div data-testid="history-page">Lịch sử</div>} />
        </Routes>
      </MemoryRouter>,
    );

    const submit = await screen.findByTestId("check-in-submit");
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-DuplicateCheckIn")).toBeInTheDocument();
    });

    const historyButton = screen.getByRole("button", { name: "Xem lịch sử" });
    expect(screen.getByTestId("duplicate-history-link")).toBe(historyButton);
    fireEvent.click(historyButton);
    expect(screen.getByTestId("history-page")).toBeInTheDocument();
  });

  it("blocks resubmit on DuplicateCheckIn outcome (BR-04, TC-BR-04-015)", async () => {
    vi.mocked(submitCheckInWithRetry).mockResolvedValue({ outcome: "DuplicateCheckIn" });
    renderFlow(`/check-in?token=${PREVIEW_TOKEN_IDS.valid}`);

    const submit = await screen.findByTestId("check-in-submit");
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-DuplicateCheckIn")).toBeInTheDocument();
    });

    expect(screen.getByTestId("check-in-outcome-DuplicateCheckIn")).toHaveAttribute(
      "data-block-resubmit",
      "true",
    );
    expect(screen.queryByTestId("check-in-submit")).not.toBeInTheDocument();
    expect(screen.queryByTestId("qr-scanner-view")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Xem lịch sử" })).toBeInTheDocument();
  });

  it("shows GpsDisabled retry button and retries GPS capture (BR-12, NFR-19)", async () => {
    vi.mocked(captureGeolocation)
      .mockResolvedValueOnce({ ok: false, reason: "denied" })
      .mockResolvedValueOnce({
        ok: true,
        position: { latitude: 10.7627, longitude: 106.6602, accuracyMeters: 12 },
      });
    renderFlow(`/check-in?token=${PREVIEW_TOKEN_IDS.valid}`);

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-GpsDisabled")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("gps-retry-button"));

    const submit = await screen.findByTestId("check-in-submit");
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(submitCheckInWithRetry).toHaveBeenCalled();
    });
  });

  it("gates submit until GPS coordinates captured on deep link (TC-BR-12-014, BR-12)", async () => {
    let resolveGeo!: (value: Awaited<ReturnType<typeof captureGeolocation>>) => void;
    const geoPromise = new Promise<Awaited<ReturnType<typeof captureGeolocation>>>((resolve) => {
      resolveGeo = resolve;
    });
    vi.mocked(captureGeolocation).mockImplementation(() => geoPromise);

    renderFlow(`/check-in?token=${PREVIEW_TOKEN_IDS.valid}`);

    const submit = await screen.findByRole("button", { name: "Xác nhận điểm danh" });
    expect(screen.getByTestId("gps-required-badge")).toBeInTheDocument();
    expect(submit).toBeDisabled();
    expect(submitCheckInWithRetry).not.toHaveBeenCalled();

    await waitFor(() => {
      expect(captureGeolocation).toHaveBeenCalled();
    });

    resolveGeo({
      ok: true,
      position: { latitude: 10.7627, longitude: 106.6602, accuracyMeters: 12 },
    });

    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    expect(screen.queryByTestId("gps-required-badge")).not.toBeInTheDocument();

    fireEvent.click(submit);

    await waitFor(() => {
      expect(submitCheckInWithRetry).toHaveBeenCalled();
    });
  });

  it("shows NotEnrolled outcome from API (AC-07, FR-07)", async () => {
    vi.mocked(submitCheckInWithRetry).mockResolvedValue({ outcome: "NotEnrolled" });
    renderFlow(`/check-in?token=${PREVIEW_TOKEN_IDS.valid}`);

    const submit = await screen.findByTestId("check-in-submit");
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-NotEnrolled")).toBeInTheDocument();
    });
  });

  it("shows OutOfRadius outcome from API (AC-08, BR-02)", async () => {
    vi.mocked(submitCheckInWithRetry).mockResolvedValue({
      outcome: "OutOfRadius",
      message: "Bạn đang ngoài phạm vi phòng học",
    });
    renderFlow(`/check-in?token=${PREVIEW_TOKEN_IDS.valid}`);

    const submit = await screen.findByTestId("check-in-submit");
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-OutOfRadius")).toBeInTheDocument();
    });
    expect(screen.getByTestId("check-in-outcome-OutOfRadius")).toHaveTextContent(
      /ngoài phạm vi phòng học/i,
    );
  });

  it("submits scanned QR token via manual paste without URL token (TC-FR-07-013, BR-03)", async () => {
    renderFlow("/check-in");

    const input = await screen.findByTestId("qr-manual-input");
    fireEvent.change(input, {
      target: {
        value: `wecheck://check-in?token=${PREVIEW_TOKEN_IDS.valid}&session=30000000-0000-4000-8000-000000000301`,
      },
    });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(captureGeolocation).toHaveBeenCalledWith(
        expect.objectContaining({ tokenId: PREVIEW_TOKEN_IDS.valid }),
      );
    });

    const submit = await screen.findByTestId("check-in-submit");
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(submitCheckInWithRetry).toHaveBeenCalled();
    });
  });

  it("passes mockLocationDetected when preview hook enabled (TC-AC-10-009, FR-10)", async () => {
    vi.mocked(readMockLocationDetected).mockReturnValue(true);
    vi.mocked(submitCheckInWithRetry).mockResolvedValue({ outcome: "SpoofSuspected" });
    renderFlow(`/check-in?token=${PREVIEW_TOKEN_IDS.valid}&mockLocation=1`);

    const submit = await screen.findByTestId("check-in-submit");
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(submitCheckInWithRetry).toHaveBeenCalledWith(
        expect.objectContaining({
          spoofMetadata: expect.objectContaining({ mockLocationDetected: true }),
        }),
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-SpoofSuspected")).toBeInTheDocument();
    });
  });

  it("expires session on submit when preview hook set (TC-AC-02-013)", async () => {
    vi.mocked(readExpireSessionOnSubmit).mockReturnValue(true);
    vi.mocked(submitCheckInWithRetry).mockResolvedValue({
      outcome: "NetworkError",
      requiresAuth: true,
      sessionExpired: true,
    });

    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, href: "" },
    });

    renderFlow(`/check-in?token=${PREVIEW_TOKEN_IDS.valid}&expireSessionOnSubmit=1`);

    const submit = await screen.findByTestId("check-in-submit");
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(previewExpireSession).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(window.location.href).toContain("/login?returnUrl=");
    });

    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("forces scanner step when cameraSim=deny even with token deep link (TC-NFR-19-016)", async () => {
    setWindowSearch("?token=valid-token-id&cameraSim=deny&platform=ios");
    renderFlow("/check-in?token=valid-token-id&cameraSim=deny&platform=ios");
    expect(screen.getByTestId("qr-scanner-view")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("camera-denied-alert")).toBeInTheDocument();
      expect(screen.getByTestId("permission-guide-modal-camera")).toBeInTheDocument();
    });
  });

  it("shows camera consent before scanner when clearConsent=1 (TC-NFR-19-020)", () => {
    setWindowSearch("?clearConsent=1");
    localStorage.setItem(LOCATION_CONSENT_KEY, "1");
    localStorage.setItem(CAMERA_CONSENT_KEY, "1");
    renderFlow("/check-in?clearConsent=1");
    expect(screen.getByTestId("camera-consent-banner")).toBeInTheDocument();
  });

  it("recovers from ExpiredQr via Quét lại and fresh scan (TC-BR-03-018)", async () => {
    vi.mocked(submitCheckInWithRetry)
      .mockResolvedValueOnce({ outcome: "ExpiredQr" })
      .mockResolvedValueOnce({ outcome: "Present" });

    renderFlow(`/check-in?token=stale-token-id`);

    const submit = await screen.findByTestId("check-in-submit");
    await waitFor(() => {
      expect(submit).not.toBeDisabled();
    });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-ExpiredQr")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Quét lại" }));

    await waitFor(() => {
      expect(screen.getByTestId("qr-scanner-view")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Quét mã QR" }));

    const resubmit = await screen.findByTestId("check-in-submit");
    await waitFor(() => {
      expect(resubmit).not.toBeDisabled();
    });
    fireEvent.click(resubmit);

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-Present")).toBeInTheDocument();
    });
  });
});
