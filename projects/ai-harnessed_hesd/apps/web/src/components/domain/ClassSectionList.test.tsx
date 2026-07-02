/**
 * Traceability: FR-06 FR-04
 * TC-FR-06-013 TC-FR-04-010
 */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ClassSectionList } from "./ClassSectionList";

vi.mock("../../lib/api/academic-api", () => ({
  fetchClassSections: vi.fn(),
}));

import { fetchClassSections } from "../../lib/api/academic-api";

describe("ClassSectionList (FR-06 FR-04)", () => {
  beforeEach(() => {
    vi.mocked(fetchClassSections).mockResolvedValue({
      ok: true,
      items: [
        {
          id: "50000000-0000-4000-8000-000000000001",
          sectionCode: "SE101-01",
          termId: "20000000-0000-4000-8000-000000000001",
          courseId: "30000000-0000-4000-8000-000000000001",
          lecturerUserId: "60000000-0000-4000-8000-000000000001",
          defaultRoomId: null,
          capacity: 60,
          isActive: true,
        },
      ],
      pagination: { page: 1, pageSize: 25, totalItems: 1, totalPages: 1 },
    });
  });

  it("TC-FR-06-013: renders section row with enrollment import link", async () => {
    render(
      <MemoryRouter initialEntries={["/admin/class-sections"]}>
        <ClassSectionList />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("SE101-01")).toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: "Nhập đăng ký" })).toHaveAttribute(
      "href",
      "/admin/class-sections/50000000-0000-4000-8000-000000000001/enrollments",
    );
  });
});
