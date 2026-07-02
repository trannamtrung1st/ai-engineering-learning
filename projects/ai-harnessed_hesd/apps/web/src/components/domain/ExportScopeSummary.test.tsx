import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExportScopeSummary } from "./ExportScopeSummary";

/** Traceability: FR-27 BR-18 AC-15 */
describe("ExportScopeSummary — FR-27", () => {
  it("renders explicit lecturer scope, filters, row count, and CSV governance copy", () => {
    render(
      <ExportScopeSummary
        roles={["Lecturer"]}
        query={{
          termId: "term-1",
          classSectionId: "section-1",
          status: "Absent",
          from: "2026-02-01",
          to: "2026-02-28",
          sortBy: "date",
          sortOrder: "desc",
          page: 1,
          pageSize: 25,
        }}
        termOptions={[{ value: "term-1", label: "HK 2026" }]}
        sectionOptions={[{ value: "section-1", label: "SE101-01" }]}
        totalItems={12}
      />,
    );

    expect(screen.getByRole("heading", { name: "Xác nhận phạm vi xuất CSV" })).toBeInTheDocument();
    expect(screen.getByText("Giảng viên · chỉ các lớp được phân công")).toBeInTheDocument();
    expect(screen.getByText("HK 2026")).toBeInTheDocument();
    expect(screen.getByText("SE101-01")).toBeInTheDocument();
    expect(screen.getByText("Absent")).toBeInTheDocument();
    expect(screen.getByText("12 bản ghi trong phạm vi đã lọc")).toBeInTheDocument();
  });
});
