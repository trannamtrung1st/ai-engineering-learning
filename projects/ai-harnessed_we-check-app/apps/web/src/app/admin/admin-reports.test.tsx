import { UserRole } from "@wecheck/domain";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { AdminExportPage } from "@/app/admin/export/page";
import { AdminReportsPage } from "@/app/admin/reports/page";
import type { AuthOutletContext } from "@/components/auth/require-auth";
import { reportCopy } from "@/lib/copy/report-labels";

function renderWithRole(
  ui: React.ReactElement,
  role: AuthOutletContext["user"]["role"],
  path = "/",
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

  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<Outlet context={context} />}>
          <Route path="*" element={ui} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

/** NFR-17 / AC-12 / AC-13 — admin report and export RBAC shells */
describe("Admin report pages (NFR-17)", () => {
  it("AdminReportsPage shows Vietnamese filter labels, summary cards, and table headers", () => {
    renderWithRole(<AdminReportsPage />, UserRole.TrainingOfficeAdmin, "/admin/reports");

    expect(screen.getByTestId("admin-reports-page")).toBeInTheDocument();
    expect(screen.getByTestId("report-filter-bar")).toBeInTheDocument();
    expect(screen.getByLabelText(reportCopy.filterClass)).toBeInTheDocument();
    expect(screen.getByLabelText(reportCopy.filterSubject)).toBeInTheDocument();
    expect(screen.getByLabelText(reportCopy.filterFromDate)).toBeInTheDocument();
    expect(screen.getByLabelText(reportCopy.filterToDate)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: reportCopy.filterApply })).toBeInTheDocument();
    expect(screen.getByTestId("report-summary-cards")).toBeInTheDocument();
    expect(screen.getByText(reportCopy.summaryTotalSessions)).toBeInTheDocument();
    expect(screen.getByText(reportCopy.summaryAvgAttendance)).toBeInTheDocument();
    expect(screen.getByText(reportCopy.summaryTotalAbsent)).toBeInTheDocument();
    expect(screen.getByText(reportCopy.summaryTotalExcused)).toBeInTheDocument();
    expect(screen.getByTestId("session-report-table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: reportCopy.colDate })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: reportCopy.colClass })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: reportCopy.colSubject })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: reportCopy.colAttendanceRate })).toBeInTheDocument();
  });

  it("AdminExportPage denies Instructor with Vietnamese export-restriction message", () => {
    renderWithRole(<AdminExportPage />, UserRole.Instructor, "/admin/export");

    expect(screen.getByTestId("admin-export-page")).toBeInTheDocument();
    expect(screen.getByText(reportCopy.exportDenied)).toBeInTheDocument();
    expect(screen.queryByText(reportCopy.exportButton)).not.toBeInTheDocument();
  });

  it("AdminExportPage shows export form for TrainingOfficeAdmin", () => {
    renderWithRole(<AdminExportPage />, UserRole.TrainingOfficeAdmin, "/admin/export");

    expect(screen.getByRole("button", { name: reportCopy.exportButton })).toBeInTheDocument();
    expect(screen.queryByText(reportCopy.exportDenied)).not.toBeInTheDocument();
  });
});
