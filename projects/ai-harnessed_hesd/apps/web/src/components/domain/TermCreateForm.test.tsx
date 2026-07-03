/**
 * Traceability: FR-01
 * TC-FR-01-011
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TermCreateForm } from "./TermCreateForm";

vi.mock("../../lib/api/academic-api", () => ({
  createTerm: vi.fn(),
}));

import { createTerm } from "../../lib/api/academic-api";

describe("TermCreateForm (FR-01)", () => {
  it("TC-FR-01-011: submits FRM-02 create term payload", () => {
    vi.mocked(createTerm).mockResolvedValue({
      ok: true,
      data: {
        id: "term-1",
        code: "2026-2",
        name: "HK 2",
        startDate: "2026-07-01",
        endDate: "2026-12-31",
        isActive: true,
      },
    });

    render(<TermCreateForm />);

    fireEvent.change(screen.getByPlaceholderText("2026-2"), { target: { value: "2026-2" } });
    fireEvent.change(screen.getByPlaceholderText("Học kỳ 2 năm 2026"), {
      target: { value: "HK 2" },
    });
    fireEvent.change(screen.getByLabelText("Ngày bắt đầu"), { target: { value: "2026-07-01" } });
    fireEvent.change(screen.getByLabelText("Ngày kết thúc"), { target: { value: "2026-12-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Tạo học kỳ" }));

    expect(createTerm).toHaveBeenCalledWith(
      expect.objectContaining({ code: "2026-2", name: "HK 2", isActive: true }),
    );
  });
});
