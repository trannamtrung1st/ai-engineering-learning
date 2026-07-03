/**
 * Traceability: FR-06
 * TC-FR-06-013
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ClassSectionCreateForm } from "./ClassSectionCreateForm";

vi.mock("../../lib/api/academic-api", () => ({
  createClassSection: vi.fn(),
  fetchTerms: vi.fn(),
  fetchCourses: vi.fn(),
  fetchRooms: vi.fn(),
}));

import { createClassSection, fetchCourses, fetchRooms, fetchTerms } from "../../lib/api/academic-api";

describe("ClassSectionCreateForm (FR-06)", () => {
  beforeEach(() => {
    vi.mocked(fetchTerms).mockResolvedValue({
      ok: true,
      items: [
        {
          id: "20000000-0000-4000-8000-000000000001",
          code: "2026-1",
          name: "HK 1",
          startDate: "2026-01-15",
          endDate: "2026-06-30",
          isActive: true,
        },
      ],
      pagination: { page: 1, pageSize: 100, totalItems: 1, totalPages: 1 },
    });
    vi.mocked(fetchCourses).mockResolvedValue({
      ok: true,
      items: [
        {
          id: "30000000-0000-4000-8000-000000000001",
          code: "SE101",
          name: "Nhập môn",
          facultyId: "10000000-0000-4000-8000-000000000001",
          creditUnits: 3,
          isActive: true,
        },
      ],
      pagination: { page: 1, pageSize: 100, totalItems: 1, totalPages: 1 },
    });
    vi.mocked(fetchRooms).mockResolvedValue({
      ok: true,
      items: [
        {
          id: "40000000-0000-4000-8000-000000000001",
          code: "A101",
          name: "Phòng A101",
          building: "Tòa A",
          isActive: true,
        },
      ],
      pagination: { page: 1, pageSize: 100, totalItems: 1, totalPages: 1 },
    });
    vi.mocked(createClassSection).mockResolvedValue({
      ok: true,
      data: {
        id: "section-new",
        sectionCode: "SE101-02",
        termId: "20000000-0000-4000-8000-000000000001",
        courseId: "30000000-0000-4000-8000-000000000001",
        lecturerUserId: "60000000-0000-4000-8000-000000000001",
        defaultRoomId: null,
        capacity: 60,
        isActive: true,
        generatedSessionCount: 12,
      },
    });
  });

  it("TC-FR-06-013: submits FRM-04 with schedule template", async () => {
    render(<ClassSectionCreateForm />);

    await waitFor(() => {
      expect(screen.getByText("Chọn học kỳ")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText("SE101-02"), { target: { value: "SE101-02" } });
    fireEvent.change(screen.getByLabelText("Học kỳ"), {
      target: { value: "20000000-0000-4000-8000-000000000001" },
    });
    fireEvent.change(screen.getByLabelText("Học phần"), {
      target: { value: "30000000-0000-4000-8000-000000000001" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tạo lớp học phần" }));

    expect(createClassSection).toHaveBeenCalledWith(
      expect.objectContaining({
        sectionCode: "SE101-02",
        scheduleTemplate: expect.objectContaining({
          dayOfWeek: "Monday",
          startTime: "08:00",
        }),
      }),
    );
  });
});
