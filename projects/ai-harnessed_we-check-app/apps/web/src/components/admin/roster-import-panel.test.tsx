import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RosterImportPanel } from "@/components/admin/roster-import-panel";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/roster-api", () => ({
  postRosterImport: vi.fn(),
  pollImportBatchUntilComplete: vi.fn(),
}));

import {
  pollImportBatchUntilComplete,
  postRosterImport,
} from "@/lib/roster-api";
import { toast } from "sonner";

const VALID_CSV =
  "institutional_id,display_name,class_code,subject_code\n" +
  "SV2026101,Nguyễn Văn A,HESD-01,SWE-101\n" +
  "SV2026102,Trần Thị B,HESD-01,SWE-101\n";

const MIXED_CSV =
  "institutional_id,display_name,class_code,subject_code\n" +
  "SV2026103,Nguyễn Văn C,HESD-01,SWE-101\n" +
  "SV2026103,Nguyễn Văn C,HESD-01,SWE-101\n";

function makeFile(content: string, name = "roster.csv"): File {
  return new File([content], name, { type: "text/csv" });
}

function ensureFileTextPolyfill() {
  if (typeof File !== "undefined" && !File.prototype.text) {
    File.prototype.text = function textPolyfill(this: File) {
      return new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = () => reject(reader.error);
        reader.readAsText(this);
      });
    };
  }
}

/** FR-03 / AC-03 — roster CSV import panel */
describe("RosterImportPanel (FR-03, AC-03)", () => {
  beforeEach(() => {
    ensureFileTextPolyfill();
    vi.clearAllMocks();
  });

  function renderPanel() {
    return render(
      <MemoryRouter>
        <RosterImportPanel />
      </MemoryRouter>,
    );
  }

  it("TC-AC-03-016 / TC-FR-03-018: shows import summary counts after successful import", async () => {
    vi.mocked(postRosterImport)
      .mockResolvedValueOnce({
        ok: true,
        status: 202,
        data: {
          batchId: "dry-batch",
          status: "Processing",
          successRows: 0,
          errorRows: 0,
          errorDetails: [],
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 202,
        data: {
          batchId: "import-batch",
          status: "Processing",
          successRows: 0,
          errorRows: 0,
          errorDetails: [],
        },
      });

    vi.mocked(pollImportBatchUntilComplete)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          batchId: "dry-batch",
          status: "Completed",
          successRows: 2,
          errorRows: 0,
          errorDetails: [],
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          batchId: "import-batch",
          status: "Completed",
          successRows: 2,
          errorRows: 0,
          errorDetails: [],
        },
      });

    renderPanel();

    const input = screen.getByTestId("roster-csv-file-input");
    fireEvent.change(input, { target: { files: [makeFile(VALID_CSV)] } });

    expect(screen.getByTestId("roster-selected-file")).toHaveTextContent("roster.csv");

    fireEvent.click(screen.getByTestId("roster-import-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("roster-import-validation-summary")).toHaveTextContent(
        "2 dòng hợp lệ, 0 dòng lỗi",
      );
    });

    fireEvent.click(screen.getByTestId("roster-import-confirm"));

    await waitFor(() => {
      expect(screen.getByTestId("roster-import-summary")).toHaveTextContent(
        "Đã nhập 2 dòng thành công",
      );
    });

    expect(toast.success).toHaveBeenCalled();
  });

  it("TC-AC-03-017 / TC-FR-03-019: partial import shows accepted/rejected counts and expandable errors", async () => {
    vi.mocked(postRosterImport).mockResolvedValue({
      ok: true,
      status: 202,
      data: {
        batchId: "batch-1",
        status: "Processing",
        successRows: 0,
        errorRows: 0,
        errorDetails: [],
      },
    });

    const duplicateError = {
      rowNumber: 3,
      errorCode: "DuplicateEnrollment",
      message: "Sinh viên đã được ghi danh cho lớp-môn này",
    };

    vi.mocked(pollImportBatchUntilComplete)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          batchId: "batch-1",
          status: "Completed",
          successRows: 1,
          errorRows: 1,
          errorDetails: [duplicateError],
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: {
          batchId: "batch-2",
          status: "Completed",
          successRows: 1,
          errorRows: 1,
          errorDetails: [duplicateError],
        },
      });

    renderPanel();

    fireEvent.change(screen.getByTestId("roster-csv-file-input"), {
      target: { files: [makeFile(MIXED_CSV)] },
    });
    fireEvent.click(screen.getByTestId("roster-import-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("roster-import-validation-summary")).toHaveTextContent(
        "1 dòng hợp lệ, 1 dòng lỗi",
      );
    });

    fireEvent.click(screen.getByTestId("roster-import-error-toggle"));

    await waitFor(() => {
      expect(screen.getByTestId("roster-import-error-row-3")).toHaveTextContent(
        "Dòng 3: Sinh viên đã được ghi danh cho lớp-môn này",
      );
    });

    fireEvent.click(screen.getByTestId("roster-import-confirm"));

    await waitFor(() => {
      expect(screen.getByTestId("roster-import-counts")).toHaveTextContent(
        "1 dòng hợp lệ, 1 dòng lỗi",
      );
    });
  });

  it("rejects non-csv file selection", () => {
    renderPanel();

    fireEvent.change(screen.getByTestId("roster-csv-file-input"), {
      target: { files: [makeFile("not csv", "notes.txt")] },
    });

    expect(screen.getByText(/Chỉ chấp nhận tệp/)).toBeInTheDocument();
    expect(screen.getByTestId("roster-import-preview")).toBeDisabled();
  });

  it("shows preview table with first rows after dry-run validation", async () => {
    vi.mocked(postRosterImport).mockResolvedValue({
      ok: true,
      status: 202,
      data: {
        batchId: "dry",
        status: "Processing",
        successRows: 0,
        errorRows: 0,
        errorDetails: [],
      },
    });
    vi.mocked(pollImportBatchUntilComplete).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        batchId: "dry",
        status: "Completed",
        successRows: 2,
        errorRows: 0,
        errorDetails: [],
      },
    });

    renderPanel();

    fireEvent.change(screen.getByTestId("roster-csv-file-input"), {
      target: { files: [makeFile(VALID_CSV)] },
    });
    fireEvent.click(screen.getByTestId("roster-import-preview"));

    await waitFor(() => {
      expect(screen.getByTestId("roster-import-preview-table")).toBeInTheDocument();
      expect(screen.getByText("SV2026101")).toBeInTheDocument();
      expect(screen.getByText("SV2026102")).toBeInTheDocument();
    });
  });
});
