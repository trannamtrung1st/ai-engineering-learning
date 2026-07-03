/**
 * Traceability: FR-04
 * TC-FR-04-010
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EnrollmentImportPanel } from "./EnrollmentImportPanel";

vi.mock("../../lib/api/academic-api", () => ({
  importEnrollments: vi.fn(),
  parseEnrollmentCsv: (text: string) =>
    text.includes("BAD")
      ? [
          { studentCode: "SV001" },
          { studentCode: "BAD" },
        ]
      : [{ studentCode: "SV001" }],
}));

import { importEnrollments } from "../../lib/api/academic-api";

describe("EnrollmentImportPanel (FR-04)", () => {
  it("TC-FR-04-010: shows accepted count and row-level rejections", async () => {
    vi.mocked(importEnrollments).mockResolvedValue({
      ok: true,
      data: {
        classSectionId: "50000000-0000-4000-8000-000000000001",
        acceptedRows: 1,
        rejectedRows: [
          { rowNumber: 2, code: "StudentNotFound", message: "Không tìm thấy mã sinh viên." },
        ],
      },
    });

    render(
      <EnrollmentImportPanel
        classSectionId="50000000-0000-4000-8000-000000000001"
        sectionLabel="SE101-01"
      />,
    );

    const file = new File(["studentCode\nSV001\nBAD"], "roster.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("Tệp CSV"), { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/roster.csv/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Nhập danh sách" }));

    await waitFor(() => {
      expect(screen.getByText(/Đã chấp nhận 1 dòng/)).toBeInTheDocument();
    });
    expect(screen.getByText("StudentNotFound")).toBeInTheDocument();
    expect(screen.getByText("SV001")).toBeInTheDocument();
  });
});
