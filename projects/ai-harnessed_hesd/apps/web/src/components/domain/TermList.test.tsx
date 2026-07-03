/**
 * Traceability: FR-01 AC-07
 * TC-FR-01-011
 */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TermList } from "./TermList";

vi.mock("../../lib/api/academic-api", () => ({
  fetchTerms: vi.fn(),
  formatTermDates: () => "01/01/2026 – 30/06/2026",
}));

import { fetchTerms } from "../../lib/api/academic-api";

describe("TermList (FR-01)", () => {
  beforeEach(() => {
    vi.mocked(fetchTerms).mockResolvedValue({
      ok: true,
      items: [
        {
          id: "20000000-0000-4000-8000-000000000001",
          code: "2026-1",
          name: "Học kỳ 1",
          startDate: "2026-01-15",
          endDate: "2026-06-30",
          isActive: true,
        },
      ],
      pagination: { page: 1, pageSize: 25, totalItems: 1, totalPages: 1 },
    });
  });

  it("TC-FR-01-011: renders term table with code and active badge", async () => {
    render(
      <MemoryRouter initialEntries={["/admin/terms"]}>
        <TermList />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("2026-1")).toBeInTheDocument();
    });
    expect(screen.getByText("Đang hoạt động")).toBeInTheDocument();
    expect(screen.getByTestId("table-toolbar")).toBeInTheDocument();
  });
});
