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

import { fetchAuthUser } from "@/lib/auth-session";
import { captureGeolocation } from "@/lib/geolocation";
import { submitCheckInWithRetry } from "@/lib/check-in-api";

/** AC-02, AC-07, AC-08, AC-09, AC-10, FR-07, FR-08, NFR-18, NFR-19 */
describe("CheckInFlow (AC-07, AC-08, FR-07, FR-08, NFR-18, NFR-19)", () => {
  beforeEach(() => {
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
    vi.clearAllMocks();
  });

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

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-ExpiredQr")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Quét lại" })).toBeInTheDocument();
  });

  it("shows TokenAlreadyUsed for consumed token from API (BR-11, AC-09)", async () => {
    vi.mocked(submitCheckInWithRetry).mockResolvedValue({ outcome: "TokenAlreadyUsed" });
    renderFlow(`/check-in?token=consumed-token-id`);

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
    vi.mocked(submitCheckInWithRetry).mockResolvedValue({ outcome: "DuplicateCheckIn" });
    render(
      <MemoryRouter initialEntries={[`/check-in?token=${PREVIEW_TOKEN_IDS.stale}`]}>
        <Routes>
          <Route path="/check-in" element={<CheckInFlow previewOutcome="DuplicateCheckIn" />} />
          <Route path="/history" element={<div data-testid="history-page">Lịch sử</div>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Xem lịch sử" }));
    expect(screen.getByTestId("history-page")).toBeInTheDocument();
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

    await waitFor(() => {
      expect(submitCheckInWithRetry).toHaveBeenCalled();
    });
  });

  it("shows NotEnrolled outcome from API (AC-07, FR-07)", async () => {
    vi.mocked(submitCheckInWithRetry).mockResolvedValue({ outcome: "NotEnrolled" });
    renderFlow(`/check-in?token=${PREVIEW_TOKEN_IDS.valid}`);

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

    await waitFor(() => {
      expect(screen.getByTestId("check-in-outcome-OutOfRadius")).toBeInTheDocument();
    });
    expect(screen.getByTestId("check-in-outcome-OutOfRadius")).toHaveTextContent(
      /ngoài phạm vi phòng học/i,
    );
  });
});
