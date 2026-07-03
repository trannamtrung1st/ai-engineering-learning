import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ManualCorrectionDialog } from "./ManualCorrectionDialog";

vi.mock("../../lib/api/roster-api.js", () => ({
  patchAttendanceCorrection: vi.fn(),
}));

import { patchAttendanceCorrection } from "../../lib/api/roster-api";

const row = {
  studentUserId: "60000000-0000-4000-8000-000000000003",
  studentCode: "SV002",
  displayName: "Lê Văn Học",
  attendanceStatus: "Absent",
  checkInMethod: null,
  checkInAt: null,
  latestAttemptOutcome: null,
};

/** Traceability: FR-20 AC-13 AC-14 AC-25 BR-14 NFR-17 */
describe("ManualCorrectionDialog — FR-20 AC-13 AC-14 AC-25 NFR-17", () => {
  beforeEach(() => {
    vi.mocked(patchAttendanceCorrection).mockReset();
  });

  it("TC-AC-13-010: gates save until reason meets minimum length", () => {
    render(
      <ManualCorrectionDialog
        sessionId="70000000-0000-4000-8000-000000000002"
        row={row}
        open
        onClose={() => undefined}
        onSuccess={() => undefined}
      />,
    );

    const saveButton = screen.getByRole("button", { name: "Lưu điều chỉnh" });
    expect(saveButton).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Lý do"), {
      target: { value: "Xác minh trực tiếp sinh viên có mặt." },
    });
    expect(saveButton).not.toBeDisabled();
  });

  it("TC-AC-14-010: surfaces escalation guidance on EditWindowExpired", async () => {
    vi.mocked(patchAttendanceCorrection).mockResolvedValue({
      ok: false,
      status: 409,
      code: "EditWindowExpired",
      message: "Hết thời gian chỉnh sửa.",
    });

    render(
      <ManualCorrectionDialog
        sessionId="70000000-0000-4000-8000-000000000002"
        row={row}
        open
        onClose={() => undefined}
        onSuccess={() => undefined}
      />,
    );

    fireEvent.change(screen.getByLabelText("Lý do"), {
      target: { value: "Xác minh trực tiếp sau khi hết cửa sổ." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Lưu điều chỉnh" }));

    await waitFor(() => {
      expect(screen.getByText(/Quản trị học vụ/)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Lưu điều chỉnh" })).toBeDisabled();
  });
});
