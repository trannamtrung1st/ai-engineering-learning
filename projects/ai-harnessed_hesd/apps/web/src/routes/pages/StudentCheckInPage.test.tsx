import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorCode } from "@attendly/domain";
import { StudentCheckInPage } from "./StudentCheckInPage";
import { clearStudentAuthentication, markStudentAuthenticated } from "../../lib/auth/auth-gate";
import { setAccessToken, clearAccessToken } from "../../lib/auth/session";

vi.mock("../../lib/api/check-in-api", () => ({
  submitCheckIn: vi.fn(),
}));

import { submitCheckIn } from "../../lib/api/check-in-api";

const submitCheckInMock = vi.mocked(submitCheckIn);

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/check-in" element={<StudentCheckInPage />} />
        <Route path="/login" element={<div>Login page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("StudentCheckInPage (AC-06 FR-16 FR-23 NFR-14)", () => {
  beforeEach(() => {
    clearStudentAuthentication();
    clearAccessToken();
    submitCheckInMock.mockReset();
  });

  it("TC-AC-06-007: redirects unauthenticated token deep link to login", () => {
    renderAt("/check-in?token=validToken");
    expect(screen.getByText("Login page")).toBeInTheDocument();
  });

  it("renders preview expired QR outcome with retry CTA", async () => {
    renderAt("/check-in?outcome=expired-qr");
    expect(screen.getByText("Mã QR đã hết hạn")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(screen.getByRole("button", { name: "Xác nhận điểm danh" })).toBeInTheDocument();
  });

  it("submits live check-in and shows Present success with timestamp", async () => {
    setAccessToken("jwt");
    submitCheckInMock.mockResolvedValue({
      ok: true,
      data: {
        outcome: "Success",
        attendanceStatus: "Present",
        classSessionId: "session-1",
        checkInAt: "2026-07-02T08:02:11Z",
      },
    });

    renderAt("/check-in?token=opaque-token");

    fireEvent.click(screen.getByRole("button", { name: "Xác nhận điểm danh" }));

    await waitFor(() => {
      expect(screen.getByText(/Điểm danh thành công.*Có mặt/)).toBeInTheDocument();
    });
    expect(submitCheckInMock).toHaveBeenCalledWith(
      expect.objectContaining({ qrToken: "opaque-token" }),
    );
  });

  it("renders localized ExpiredQr recovery after API failure", async () => {
    setAccessToken("jwt");
    submitCheckInMock.mockResolvedValue({
      ok: false,
      status: 422,
      code: ErrorCode.ExpiredQr,
      message: "Mã QR đã hết hạn",
    });

    renderAt("/check-in?token=expired");

    fireEvent.click(screen.getByRole("button", { name: "Xác nhận điểm danh" }));

    await waitFor(() => {
      expect(screen.getByText("Mã QR đã hết hạn")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
    });
  });

  it("renders duplicate info with prior Present badge and timestamp from API details", async () => {
    setAccessToken("jwt");
    submitCheckInMock.mockResolvedValue({
      ok: false,
      status: 409,
      code: ErrorCode.DuplicateCheckIn,
      message: "Bạn đã điểm danh buổi học này rồi.",
      details: {
        classSessionId: "session-1",
        attendanceStatus: "Present",
        checkInAt: "2026-07-02T08:02:11Z",
      },
    });

    renderAt("/check-in?token=opaque-token");

    fireEvent.click(screen.getByRole("button", { name: "Xác nhận điểm danh" }));

    await waitFor(() => {
      expect(screen.getByText("Bạn đã điểm danh buổi học này rồi.")).toBeInTheDocument();
      expect(screen.getByText(/Trạng thái hiện tại/)).toBeInTheDocument();
      expect(screen.getByText("Có mặt")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "Thử lại" })).not.toBeInTheDocument();
  });

  it("allows mock-authenticated preview form without access token", () => {
    markStudentAuthenticated();
    renderAt("/check-in?token=validToken");
    expect(screen.getByRole("button", { name: "Xác nhận điểm danh" })).toBeInTheDocument();
  });
});
