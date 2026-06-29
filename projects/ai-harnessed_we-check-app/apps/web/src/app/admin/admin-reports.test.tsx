import { UserRole } from "@wecheck/domain";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { AdminExportPage } from "@/app/admin/export/page";
import { AdminReportsPage } from "@/app/admin/reports/page";
import type { AuthOutletContext } from "@/components/auth/require-auth";
import { reportCopy } from "@/lib/copy/report-labels";

vi.mock("@/lib/reference-api", () => ({
  fetchClasses: vi.fn(),
  fetchSubjects: vi.fn(),
}));

vi.mock("@/lib/reports-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/reports-api")>();
  return {
    ...actual,
    fetchClassSubjectSummary: vi.fn(),
    fetchSessionSummaries: vi.fn(),
    estimateExportRowCount: vi.fn(),
    exportAttendanceCsv: vi.fn(),
  };
});

import { fetchClasses, fetchSubjects } from "@/lib/reference-api";
import {
  fetchClassSubjectSummary,
  fetchSessionSummaries,
  estimateExportRowCount,
} from "@/lib/reports-api";

const mockSummary = {
  classCode: "HESD-01",
  subjectCode: "SWE-101",
  dateFrom: "2026-06-01",
  dateTo: "2026-06-30",
  sessionsHeld: 2,
  students: [
    {
      institutionalId: "SV2026001",
      displayName: "Nguyễn Văn A",
      presentCount: 2,
      absentCount: 0,
      excusedCount: 0,
      attendanceRate: 1,
    },
  ],
};

const mockSessions = {
  items: [
    {
      sessionId: "sess-1",
      scheduledStart: "2026-06-28T08:00:00.000Z",
      classCode: "HESD-01",
      subjectCode: "SWE-101",
      enrolled: 2,
      present: 2,
      absent: 0,
      excused: 0,
    },
    {
      sessionId: "sess-2",
      scheduledStart: "2026-06-21T08:00:00.000Z",
      classCode: "HESD-02",
      subjectCode: "SWE-101",
      enrolled: 2,
      present: 1,
      absent: 1,
      excused: 0,
    },
  ],
};

function renderWithRole(
  ui: React.ReactElement,
  role: AuthOutletContext["user"]["role"],
) {
  const context: AuthOutletContext = {
    user: {
      id: "test-user",
      institutionalId: "GV2026001",
      displayName: "Người dùng thử",
      email: "test@example.edu.vn",
      role,
    },
  };

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Routes>
          <Route path="*" element={<Outlet context={context} />}>
            <Route path="*" element={ui} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** NFR-17 / AC-12 / AC-13 — admin report and export pages */
describe("Admin report pages (NFR-17)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchClasses).mockResolvedValue([
      { id: "class-1", code: "HESD-01", name: "HESD Cohort A", term: null },
      { id: "class-2", code: "HESD-02", name: "HESD Cohort B", term: null },
    ]);
    vi.mocked(fetchSubjects).mockResolvedValue([
      { id: "subject-1", code: "SWE-101", name: "Software Engineering 101" },
    ]);
    vi.mocked(fetchClassSubjectSummary).mockResolvedValue({ ok: true, data: mockSummary });
    vi.mocked(fetchSessionSummaries).mockResolvedValue({ ok: true, data: mockSessions });
    vi.mocked(estimateExportRowCount).mockResolvedValue({ ok: true, data: 3 });
  });

  it("TC-AC-12-012: AdminReportsPage shows Vietnamese filter labels, summary cards, and table headers", async () => {
    renderWithRole(<AdminReportsPage />, UserRole.TrainingOfficeAdmin);

    await waitFor(() => {
      expect(screen.getByTestId("report-filter-bar")).toBeInTheDocument();
    });

    expect(screen.getByLabelText(reportCopy.filterClass)).toBeInTheDocument();
    expect(screen.getByLabelText(reportCopy.filterSubject)).toBeInTheDocument();
    expect(screen.getByLabelText(reportCopy.filterFromDate)).toBeInTheDocument();
    expect(screen.getByLabelText(reportCopy.filterToDate)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: reportCopy.filterApply }));

    await waitFor(() => {
      expect(screen.getByTestId("report-summary-cards")).toBeInTheDocument();
    });

    expect(screen.getByText(reportCopy.summaryTotalSessions)).toBeInTheDocument();
    expect(screen.getByText(reportCopy.summaryAvgAttendance)).toBeInTheDocument();
    expect(screen.getByText(reportCopy.summaryTotalAbsent)).toBeInTheDocument();
    expect(screen.getByText(reportCopy.summaryTotalExcused)).toBeInTheDocument();
    expect(screen.getByTestId("session-report-table")).toBeInTheDocument();
    const sessionTable = screen.getByTestId("session-report-table");
    expect(sessionTable.querySelector(`th[scope="col"]`)?.textContent).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: reportCopy.colDate })).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader", { name: reportCopy.colClass }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("columnheader", { name: reportCopy.colSubject }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("columnheader", { name: reportCopy.colAttendanceRate }).length).toBeGreaterThan(0);
  });

  it("TC-AC-13-013 / BR-09: AdminExportPage denies Instructor with Vietnamese export-restriction message", () => {
    renderWithRole(<AdminExportPage />, UserRole.Instructor);

    expect(screen.getByTestId("admin-export-page")).toBeInTheDocument();
    expect(screen.getByText(reportCopy.exportDenied)).toBeInTheDocument();
    expect(screen.queryByText(reportCopy.exportButton)).not.toBeInTheDocument();
  });

  it("TC-AC-13-012: AdminExportPage shows export form for TrainingOfficeAdmin", async () => {
    renderWithRole(<AdminExportPage />, UserRole.TrainingOfficeAdmin);

    await waitFor(() => {
      expect(screen.getByTestId("report-filter-bar")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: reportCopy.filterApply }));

    await waitFor(() => {
      expect(screen.getByTestId("csv-export-panel")).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: reportCopy.exportButton })).toBeInTheDocument();
    expect(screen.queryByText(reportCopy.exportDenied)).not.toBeInTheDocument();
  });
});
