import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AttendanceReportList } from "./AttendanceReportList";

const fetchAttendanceReport = vi.fn();
const createAttendanceExport = vi.fn();
const downloadAttendanceExport = vi.fn();

vi.mock("../../lib/api/reporting-api.js", () => ({
  fetchAttendanceReport: (...args: unknown[]) => fetchAttendanceReport(...args),
  createAttendanceExport: (...args: unknown[]) => createAttendanceExport(...args),
  downloadAttendanceExport: (...args: unknown[]) => downloadAttendanceExport(...args),
}));

function renderReport(initialUrl = "/reports/attendance?termId=term-1") {
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <AttendanceReportList
        roles={["Lecturer"]}
        defaultTermId="term-1"
        termOptions={[{ value: "term-1", label: "HK 2026" }]}
        sectionOptions={[{ value: "section-1", label: "SE101-01" }]}
        canExport
      />
    </MemoryRouter>,
  );
}

const reportRow = {
  attendanceRecordId: "record-1",
  studentUserId: "60000000-0000-4000-8000-000000000002",
  studentCode: "SV001",
  classSessionId: "session-1",
  classSectionId: "section-1",
  sectionCode: "SE101-01",
  attendanceStatus: "Present",
  checkInAt: "2026-02-01T08:05:00.000Z",
  checkInMethod: "QR",
  sessionDate: "2026-02-01T08:00:00.000Z",
};

/** Traceability: FR-27 FR-28 BR-18 AC-15 AC-17 */
describe("AttendanceReportList — PG-13/PG-14", () => {
  beforeEach(() => {
    fetchAttendanceReport.mockReset();
    createAttendanceExport.mockReset();
    downloadAttendanceExport.mockReset();
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:attendance-export"),
      revokeObjectURL: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  });

  it("renders report toolbar, scoped rows, status badges, and pagination", async () => {
    fetchAttendanceReport.mockResolvedValue({
      ok: true,
      rows: [reportRow],
      pagination: { page: 1, pageSize: 25, totalItems: 1, totalPages: 1 },
    });

    renderReport();

    expect(await screen.findByTestId("attendance-report-list")).toBeInTheDocument();
    expect(screen.getByTestId("table-toolbar")).toBeInTheDocument();
    expect(screen.getByLabelText("Tìm kiếm danh sách")).toBeInTheDocument();
    expect(screen.getByLabelText("Từ ngày")).toBeInTheDocument();
    expect(screen.getByLabelText("Đến ngày")).toBeInTheDocument();
    expect(screen.getByLabelText("Sắp xếp theo")).toBeInTheDocument();
    expect(screen.getByText("SV001")).toBeInTheDocument();
    expect(screen.getAllByText("SE101-01").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByLabelText("Phương thức QR")).toBeInTheDocument();
    expect(screen.getByText("Hiển thị 1–1 / 1 bản ghi trong phạm vi được cấp")).toBeInTheDocument();
  });

  it("shows no-results copy when filters match zero scoped rows", async () => {
    fetchAttendanceReport.mockResolvedValue({
      ok: true,
      rows: [],
      pagination: { page: 1, pageSize: 25, totalItems: 0, totalPages: 1 },
    });

    renderReport("/reports/attendance?termId=term-1&status=Absent");

    expect(await screen.findByText("Không tìm thấy kết quả")).toBeInTheDocument();
    expect(
      screen.getByText("Không có bản ghi nào khớp với bộ lọc hiện tại trong phạm vi được cấp."),
    ).toBeInTheDocument();
  });

  it("confirms scope, creates export, downloads CSV, and shows completion feedback", async () => {
    fetchAttendanceReport.mockResolvedValue({
      ok: true,
      rows: [reportRow],
      pagination: { page: 1, pageSize: 25, totalItems: 1, totalPages: 1 },
    });
    createAttendanceExport.mockResolvedValue({
      ok: true,
      job: { exportJobId: "job-12345678", status: "Completed", format: "csv" },
    });
    downloadAttendanceExport.mockResolvedValue({
      ok: true,
      csv: "studentCode\nSV001",
      filename: "attendance-export-job.csv",
    });

    renderReport();

    fireEvent.click(await screen.findByRole("button", { name: "Xuất CSV" }));
    expect(screen.getByRole("heading", { name: "Xác nhận phạm vi xuất CSV" })).toBeInTheDocument();
    expect(screen.getByText("Giảng viên · chỉ các lớp được phân công")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Xác nhận xuất CSV" }));

    await waitFor(() => {
      expect(createAttendanceExport).toHaveBeenCalled();
      expect(downloadAttendanceExport).toHaveBeenCalledWith("job-12345678");
    });
    expect(await screen.findByText("Xuất CSV thành công")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tải lại CSV" })).toBeInTheDocument();
  });
});
