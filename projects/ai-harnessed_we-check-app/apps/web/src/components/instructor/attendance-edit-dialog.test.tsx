import { AttendanceStatus } from "@wecheck/domain";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AttendanceEditDialog } from "@/components/instructor/attendance-edit-dialog";

vi.mock("@/lib/attendance-roster-api", () => ({
  patchAttendanceRecord: vi.fn(),
}));

import { patchAttendanceRecord } from "@/lib/attendance-roster-api";

const sampleRecord = {
  id: "rec-1",
  studentId: "s1",
  institutionalId: "SV2026002",
  displayName: "Trần Thị B",
  status: AttendanceStatus.Absent,
  checkedInAt: null,
};

/** AC-11 / FR-11 / BR-10 — manual attendance edit dialog */
describe("AttendanceEditDialog (AC-11, FR-11, BR-10)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("TC-AC-11-011: displays student name, current status, and form fields", () => {
    render(
      <AttendanceEditDialog
        open
        record={sampleRecord}
        editAllowed
        windowExpired={false}
        hoursRemaining={22}
        onClose={() => undefined}
        onSaved={() => undefined}
      />,
    );

    expect(screen.getByTestId("attendance-edit-dialog")).toBeInTheDocument();
    expect(screen.getByText("Trần Thị B")).toBeInTheDocument();
    expect(screen.getByTestId("status-badge-Absent")).toBeInTheDocument();
    expect(screen.getByTestId("attendance-edit-status")).toBeInTheDocument();
    expect(screen.getByTestId("attendance-edit-note")).toBeInTheDocument();
    expect(screen.getByTestId("edit-window-countdown")).toHaveTextContent(/Còn 22 giờ/);
  });

  it("TC-AC-11-011: submits Absent to Present with note via API", async () => {
    const onSaved = vi.fn();
    const onClose = vi.fn();

    vi.mocked(patchAttendanceRecord).mockResolvedValue({
      ok: true,
      data: {
        id: "rec-1",
        sessionId: "sess-1",
        studentId: "s1",
        institutionalId: "SV2026002",
        displayName: "Trần Thị B",
        status: AttendanceStatus.Present,
        checkedInAt: "2026-06-29T10:00:00.000Z",
      },
    });

    render(
      <AttendanceEditDialog
        open
        record={sampleRecord}
        editAllowed
        windowExpired={false}
        hoursRemaining={22}
        onClose={onClose}
        onSaved={onSaved}
      />,
    );

    fireEvent.change(screen.getByTestId("attendance-edit-status"), {
      target: { value: AttendanceStatus.Present },
    });
    fireEvent.change(screen.getByTestId("attendance-edit-note"), {
      target: { value: "Xác minh trực tiếp tại lớp" },
    });
    fireEvent.click(screen.getByTestId("attendance-edit-submit"));

    await waitFor(() => {
      expect(patchAttendanceRecord).toHaveBeenCalledWith("rec-1", {
        status: AttendanceStatus.Present,
        note: "Xác minh trực tiếp tại lớp",
      });
    });
    expect(onSaved).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("TC-AC-11-016: defaults status to Present when current status is Pending", () => {
    render(
      <AttendanceEditDialog
        open
        record={{ ...sampleRecord, status: AttendanceStatus.Pending }}
        editAllowed
        windowExpired={false}
        hoursRemaining={null}
        onClose={() => undefined}
        onSaved={() => undefined}
      />,
    );

    expect(screen.getByTestId("attendance-edit-status")).toHaveValue(AttendanceStatus.Present);
  });

  it("TC-AC-11-012: shows expired notice and disables submit when window expired", () => {
    render(
      <AttendanceEditDialog
        open
        record={sampleRecord}
        editAllowed={false}
        windowExpired
        hoursRemaining={0}
        onClose={() => undefined}
        onSaved={() => undefined}
      />,
    );

    expect(screen.getByTestId("edit-window-expired-notice")).toHaveTextContent(
      /Đã hết thời hạn chỉnh sửa điểm danh/,
    );
    expect(screen.getByTestId("attendance-edit-submit")).toBeDisabled();
  });

  it("TC-BR-10-018: requires min 10 char note for Excused status", async () => {
    render(
      <AttendanceEditDialog
        open
        record={sampleRecord}
        editAllowed
        windowExpired={false}
        hoursRemaining={22}
        onClose={() => undefined}
        onSaved={() => undefined}
      />,
    );

    fireEvent.change(screen.getByTestId("attendance-edit-status"), {
      target: { value: AttendanceStatus.Excused },
    });
    fireEvent.change(screen.getByTestId("attendance-edit-note"), {
      target: { value: "ngắn" },
    });
    fireEvent.click(screen.getByTestId("attendance-edit-submit"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/ít nhất 10 ký tự/);
    });
    expect(patchAttendanceRecord).not.toHaveBeenCalled();
  });

  it("TC-AC-11-006: surfaces API EditWindowExpired message", async () => {
    vi.mocked(patchAttendanceRecord).mockResolvedValue({
      ok: false,
      status: 403,
      error: {
        errorCode: "EditWindowExpired",
        message: "Đã quá thời hạn chỉnh sửa điểm danh (24 giờ)",
      },
    });

    render(
      <AttendanceEditDialog
        open
        record={sampleRecord}
        editAllowed
        windowExpired={false}
        hoursRemaining={1}
        onClose={() => undefined}
        onSaved={() => undefined}
      />,
    );

    fireEvent.click(screen.getByTestId("attendance-edit-submit"));

    await waitFor(() => {
      expect(screen.getByText(/Đã quá thời hạn chỉnh sửa/)).toBeInTheDocument();
    });
  });
});
