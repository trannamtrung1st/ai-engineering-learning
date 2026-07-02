import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UserImportForm } from "@/components/admin/user-import-form";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/users-api", () => ({
  fetchAllInstitutionalIds: vi.fn(),
}));

vi.mock("@/lib/user-import-api", () => ({
  postUserImport: vi.fn(),
  pollUserImportBatchUntilComplete: vi.fn(),
}));

import { fetchAllInstitutionalIds } from "@/lib/users-api";
import {
  pollUserImportBatchUntilComplete,
  postUserImport,
} from "@/lib/user-import-api";

const csvContent = [
  "institutional_id,display_name,email,role,active",
  "SV2026100,Nguyễn Văn M,student100@example.edu.vn,Student,true",
  "SV2026001,Nguyễn Văn A,student@example.edu.vn,Student,true",
].join("\n");

/** FR-01 / AC-01 — admin user CSV import form */
describe("UserImportForm (FR-01, AC-01)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchAllInstitutionalIds).mockResolvedValue({
      ok: true,
      data: new Set(["SV2026001"]),
    });
  });

  it("TC-AC-01-017: renders upload form with file select", () => {
    render(<UserImportForm />);
    expect(screen.getByTestId("user-import-form")).toBeInTheDocument();
    expect(screen.getByTestId("user-import-file-select")).toBeInTheDocument();
    expect(screen.getByText("Tải mẫu CSV")).toBeInTheDocument();
  });

  it("TC-FR-01-024: preview shows create and update row status", async () => {
    vi.mocked(postUserImport).mockResolvedValue({
      ok: true,
      status: 202,
      data: { batchId: "batch-1", status: "Processing", successRows: 0, errorRows: 0, errorDetails: [] },
    });
    vi.mocked(pollUserImportBatchUntilComplete).mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        batchId: "batch-1",
        status: "Completed",
        totalRows: 2,
        successRows: 2,
        errorRows: 0,
        createdCount: 1,
        updatedCount: 1,
        errorDetails: [],
      },
    });

    render(<UserImportForm />);
    const file = new File([csvContent], "users.csv", { type: "text/csv" });
    Object.defineProperty(file, "text", {
      configurable: true,
      value: () => Promise.resolve(csvContent),
    });
    fireEvent.change(screen.getByTestId("user-import-file-select"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByTestId("user-import-preview-button"));

    await waitFor(() => {
      expect(screen.getByTestId("user-import-preview-table")).toBeInTheDocument();
    });
    expect(screen.getByTestId("user-import-row-status-2")).toHaveTextContent("Tạo mới");
    expect(screen.getByTestId("user-import-row-status-3")).toHaveTextContent("Cập nhật");
  });
});
