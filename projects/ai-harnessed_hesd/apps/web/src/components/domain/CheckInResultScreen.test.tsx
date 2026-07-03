import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CheckInResultScreen } from "./CheckInResultScreen";

describe("CheckInResultScreen (NFR-14)", () => {
  it("renders expired QR failure with retry CTA", () => {
    render(
      <CheckInResultScreen
        state="failure-expired-qr"
        title="Mã QR đã hết hạn"
        message="Mã QR đã hết hạn. Vui lòng quét mã mới."
        retryAllowed
        onRetry={() => undefined}
      />,
    );

    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();
  });

  it("renders duplicate info without retry CTA", () => {
    render(
      <CheckInResultScreen
        state="failure-duplicate"
        title="Đã điểm danh"
        message="Bạn đã điểm danh buổi học này rồi."
        retryAllowed={false}
        attendanceStatus="Present"
        timestamp="08:02"
      />,
    );

    expect(screen.queryByRole("button", { name: "Thử lại" })).not.toBeInTheDocument();
    expect(screen.getByText(/Trạng thái hiện tại/)).toBeInTheDocument();
  });
});
