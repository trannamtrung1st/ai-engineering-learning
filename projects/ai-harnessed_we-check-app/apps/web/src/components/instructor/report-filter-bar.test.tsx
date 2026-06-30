import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { InstructorReportFilterBar } from "@/components/instructor/instructor-report-filter-bar";
import { reportCopy } from "@/lib/copy/report-labels";

vi.mock("@/lib/reference-api", () => ({
  fetchClasses: vi.fn(),
  fetchSubjects: vi.fn(),
}));

import { fetchClasses, fetchSubjects } from "@/lib/reference-api";

/** FR-12 / AC-12 / BR-08 — instructor report filter bar */
describe("InstructorReportFilterBar (AC-12, FR-12, BR-08)", () => {
  beforeEach(() => {
    vi.mocked(fetchClasses).mockResolvedValue([
      { id: "class-1", code: "HESD-01", name: "HESD Cohort A", term: null },
    ]);
    vi.mocked(fetchSubjects).mockResolvedValue([
      { id: "subject-1", code: "SWE-101", name: "Software Engineering 101" },
    ]);
  });

  it("TC-AC-12-011: renders Vietnamese filter labels for assigned scope", async () => {
    render(<InstructorReportFilterBar onApply={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("report-filter-bar")).toBeInTheDocument();
    });

    expect(screen.getByLabelText(reportCopy.filterClass)).toBeInTheDocument();
    expect(screen.getByLabelText(reportCopy.filterSubject)).toBeInTheDocument();
    expect(screen.getByLabelText(reportCopy.filterFromDate)).toBeInTheDocument();
    expect(screen.getByLabelText(reportCopy.filterToDate)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: reportCopy.filterApply })).toBeInTheDocument();
  });

  it("TC-BR-08-011: lists only instructor-assigned class and subject options from API", async () => {
    render(<InstructorReportFilterBar onApply={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByLabelText(reportCopy.filterClass)).toHaveValue("HESD-01");
    });

    const classSelect = screen.getByLabelText(reportCopy.filterClass);
    expect(classSelect).toHaveDisplayValue("HESD-01");
    expect(classSelect.querySelectorAll("option")).toHaveLength(1);

    const subjectSelect = screen.getByLabelText(reportCopy.filterSubject);
    expect(subjectSelect).toHaveDisplayValue("SWE-101");
    expect(subjectSelect.querySelectorAll("option")).toHaveLength(1);
  });

  it("TC-FR-12-011: calls onApply with class, subject, and date range", async () => {
    const onApply = vi.fn();
    render(
      <InstructorReportFilterBar
        onApply={onApply}
        initialFilters={{
          classCode: "HESD-01",
          subjectCode: "SWE-101",
          from: "2026-06-01",
          to: "2026-06-30",
        }}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: reportCopy.filterApply })).toBeEnabled();
    });

    fireEvent.click(screen.getByRole("button", { name: reportCopy.filterApply }));

    expect(onApply).toHaveBeenCalledWith({
      classCode: "HESD-01",
      subjectCode: "SWE-101",
      from: "2026-06-01",
      to: "2026-06-30",
    });
  });
});
