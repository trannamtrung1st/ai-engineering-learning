import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { CsvExportPanel } from "@/components/admin/csv-export-panel";
import { reportCopy } from "@/lib/copy/report-labels";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/reports-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/reports-api")>();
  return {
    ...actual,
    estimateExportRowCount: vi.fn(),
    exportAttendanceCsv: vi.fn(),
    downloadBlob: vi.fn(),
  };
});

import {
  downloadBlob,
  estimateExportRowCount,
  exportAttendanceCsv,
} from "@/lib/reports-api";

const filters = {
  classCode: "HESD-01",
  subjectCode: "SWE-101",
  from: "2026-06-01",
  to: "2026-06-30",
};

/** FR-13 / AC-13 / BR-09 / NFR-11 — admin CSV export panel */
describe("CsvExportPanel (FR-13, AC-13, BR-09)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(estimateExportRowCount).mockResolvedValue({ ok: true, data: 5 });
    vi.mocked(exportAttendanceCsv).mockResolvedValue({
      ok: true,
      data: { blob: new Blob(["csv"]), filename: "attendance-export-2026-06-30.csv" },
    });
  });

  it("TC-AC-13-012: shows estimating then ready state with row estimate from HEAD dry-run", async () => {
    render(<CsvExportPanel filters={filters} />);

    expect(screen.getByTestId("csv-export-estimating")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("csv-export-row-estimate")).toHaveTextContent("5");
    });

    expect(estimateExportRowCount).toHaveBeenCalledWith(filters);
    expect(screen.getByRole("button", { name: reportCopy.exportButton })).toBeEnabled();
  });

  it("TC-FR-13-012: opens confirm dialog with compliance note and exports CSV on confirm", async () => {
    render(<CsvExportPanel filters={filters} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: reportCopy.exportButton })).toBeEnabled();
    });

    fireEvent.click(screen.getByRole("button", { name: reportCopy.exportButton }));

    expect(screen.getByTestId("csv-export-confirm-dialog")).toBeInTheDocument();
    expect(screen.getByText(reportCopy.exportConfirmCompliance)).toBeInTheDocument();
    expect(screen.getByTestId("export-confirm-row-count")).toHaveTextContent("5");

    fireEvent.click(screen.getByTestId("export-confirm-submit"));

    await waitFor(() => {
      expect(exportAttendanceCsv).toHaveBeenCalledWith(filters);
    });

    expect(downloadBlob).toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith(reportCopy.exportSuccess);
  });

  it("TC-AC-13-012: disables export when estimated rows are zero", async () => {
    vi.mocked(estimateExportRowCount).mockResolvedValue({ ok: true, data: 0 });

    render(<CsvExportPanel filters={filters} />);

    await waitFor(() => {
      expect(screen.getByText(reportCopy.exportNoRows)).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: reportCopy.exportButton })).toBeDisabled();
  });
});
