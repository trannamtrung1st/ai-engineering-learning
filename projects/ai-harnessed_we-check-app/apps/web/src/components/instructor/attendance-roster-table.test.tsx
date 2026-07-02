import { AttendanceStatus, SessionStatus, UserRole } from "@wecheck/domain";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AttendanceRosterTable } from "@/components/instructor/attendance-roster-table";
import type { SessionMonitorData } from "@/lib/session-monitor-api";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/components/auth/require-auth", () => ({
  useAuthUser: vi.fn(),
}));

vi.mock("@/hooks/use-session-roster", () => ({
  useSessionRoster: vi.fn(),
  useInvalidateSessionRoster: vi.fn(() => vi.fn()),
}));

vi.mock("@/components/domain/attendance/attendance-audit-trail", () => ({
  AttendanceAuditTrail: () => <div data-testid="attendance-audit-trail-stub" />,
}));

vi.mock("@/components/instructor/attendance-edit-dialog", () => ({
  AttendanceEditDialog: ({
    open,
    record,
    editAllowed,
    windowExpired,
    onClose,
    onSaved,
  }: {
    open: boolean;
    record: { displayName: string; status: string } | null;
    editAllowed: boolean;
    windowExpired: boolean;
    onClose: () => void;
    onSaved: (record: { status: string }, note: string) => void;
  }) =>
    open && record ? (
      <div data-testid="attendance-edit-dialog-stub">
        <span data-testid="dialog-record-name">{record.displayName}</span>
        <span data-testid="dialog-edit-allowed">{String(editAllowed)}</span>
        <span data-testid="dialog-window-expired">{String(windowExpired)}</span>
        <button
          type="button"
          data-testid="dialog-save-stub"
          onClick={() => onSaved({ ...record, status: AttendanceStatus.Present }, "Xác minh trực tiếp tại lớp")}
        >
          Lưu
        </button>
        <button type="button" onClick={onClose}>
          Đóng
        </button>
      </div>
    ) : null,
}));

import { useAuthUser } from "@/components/auth/require-auth";
import { useSessionRoster } from "@/hooks/use-session-roster";
import { toast } from "sonner";

const rosterData: SessionMonitorData = {
  summary: {
    enrolled: 3,
    present: 1,
    pending: 0,
    absent: 2,
    excused: 0,
    rejected: 0,
  },
  records: [
    {
      id: "rec-1",
      studentId: "s1",
      institutionalId: "SV2026001",
      displayName: "Nguyễn Văn A",
      status: AttendanceStatus.Present,
      checkedInAt: "2026-06-29T08:05:00.000Z",
    },
    {
      id: "rec-2",
      studentId: "s2",
      institutionalId: "SV2026002",
      displayName: "Trần Thị B",
      status: AttendanceStatus.Absent,
      checkedInAt: null,
    },
    {
      id: "rec-3",
      studentId: "s3",
      institutionalId: "SV2026003",
      displayName: "Lê Văn C",
      status: AttendanceStatus.Absent,
      checkedInAt: null,
    },
  ],
  alerts: { codeSharing: false },
};

function mockRoster(overrides: Partial<ReturnType<typeof useSessionRoster>> = {}) {
  vi.mocked(useSessionRoster).mockReturnValue({
    data: rosterData,
    isLoading: false,
    isError: false,
    ...overrides,
  } as ReturnType<typeof useSessionRoster>);
}

function renderTable(props: Partial<ComponentProps<typeof AttendanceRosterTable>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AttendanceRosterTable
        sessionId="sess-1"
        sessionStatus={SessionStatus.Closed}
        closedAt={new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString()}
        {...props}
      />
    </QueryClientProvider>,
  );
}

/** AC-11 / FR-11 / BR-10 — attendance roster grid */
describe("AttendanceRosterTable (AC-11, FR-11, BR-10)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useAuthUser).mockReturnValue({
      id: "inst-1",
      institutionalId: "GV001",
      displayName: "Giảng viên Nguyễn Văn B",
      email: "instructor@example.edu.vn",
      role: UserRole.Instructor,
    });
    mockRoster();
  });

  it("TC-AC-11-011: renders roster columns and Absent row with Chỉnh sửa enabled within edit window", () => {
    renderTable();

    expect(screen.getByTestId("attendance-roster-table")).toBeInTheDocument();
    expect(screen.getByText("Mã SV")).toBeInTheDocument();
    expect(screen.getByText("Họ tên")).toBeInTheDocument();
    expect(screen.getByTestId("roster-row-sv2026002")).toBeInTheDocument();
    expect(
      screen.getByTestId("roster-row-sv2026002").querySelector('[data-testid="status-badge-Absent"]'),
    ).toBeInTheDocument();
    expect(screen.getByTestId("roster-edit-sv2026002")).toBeEnabled();
  });

  it("TC-AC-11-011: opens edit dialog when Chỉnh sửa clicked", async () => {
    renderTable();

    fireEvent.click(screen.getByTestId("roster-edit-sv2026002"));

    await waitFor(() => {
      expect(screen.getByTestId("attendance-edit-dialog-stub")).toBeInTheDocument();
    });
    expect(screen.getByTestId("dialog-record-name")).toHaveTextContent("Trần Thị B");
    expect(screen.getByTestId("dialog-edit-allowed")).toHaveTextContent("true");
  });

  it("TC-AC-11-011: successful save shows toast", async () => {
    renderTable();

    fireEvent.click(screen.getByTestId("roster-edit-sv2026002"));
    fireEvent.click(screen.getByTestId("dialog-save-stub"));

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Đã cập nhật điểm danh");
    });
  });

  it("TC-AC-11-012: disables Chỉnh sửa when instructor edit window expired", () => {
    const closedAt = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString();
    renderTable({ closedAt });

    expect(screen.getByTestId("roster-edit-sv2026002")).toBeDisabled();
    expect(screen.getByTestId("roster-edit-window-notice")).toHaveTextContent(
      /Đã hết thời hạn chỉnh sửa/,
    );
  });

  it("TC-AC-11-012: admin retains edit when instructor window expired", () => {
    vi.mocked(useAuthUser).mockReturnValue({
      id: "admin-1",
      institutionalId: "ADMIN001",
      displayName: "Quản trị",
      email: "admin@example.edu.vn",
      role: UserRole.TrainingOfficeAdmin,
    });

    const closedAt = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString();
    renderTable({ closedAt });

    expect(screen.getByTestId("roster-edit-sv2026002")).toBeEnabled();
  });

  it("TC-FR-11-011: status filter shows only Absent rows", () => {
    renderTable();

    fireEvent.change(screen.getByTestId("roster-status-filter"), {
      target: { value: AttendanceStatus.Absent },
    });

    expect(screen.getByTestId("roster-row-sv2026002")).toBeInTheDocument();
    expect(screen.queryByTestId("roster-row-sv2026001")).not.toBeInTheDocument();
  });

  it("TC-FR-11-021: student search filters roster by displayName and institutionalId", () => {
    renderTable();

    expect(screen.getByTestId("roster-toolbar")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Tìm sinh viên…")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("roster-student-search"), {
      target: { value: "Nguyễn" },
    });
    expect(screen.getByTestId("roster-row-sv2026001")).toBeInTheDocument();
    expect(screen.queryByTestId("roster-row-sv2026002")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("roster-search-clear"));
    expect(screen.getByTestId("roster-student-search")).toHaveValue("");

    fireEvent.change(screen.getByTestId("roster-student-search"), {
      target: { value: "SV2026003" },
    });
    expect(screen.getByTestId("roster-row-sv2026003")).toBeInTheDocument();
    expect(screen.queryByTestId("roster-row-sv2026001")).not.toBeInTheDocument();
  });

  it("TC-FR-11-021: column sort toggles Trạng thái order", () => {
    renderTable();

    fireEvent.click(screen.getByTestId("roster-sort-status"));
    expect(screen.getByTestId("roster-sort-status")).toHaveAttribute("aria-sort", "ascending");
  });
});
