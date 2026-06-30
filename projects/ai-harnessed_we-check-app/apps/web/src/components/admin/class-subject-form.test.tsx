import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ClassSubjectForm } from "@/components/admin/class-subject-form";

const navigateMock = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/reference-api", () => ({
  createClass: vi.fn(),
  createSubject: vi.fn(),
  mapReferenceApiErrorToFieldErrors: vi.fn((error: { errorCode?: string; message?: string }) => {
    if (error.errorCode === "DuplicateClassCode") {
      return { classCode: error.message ?? "Mã lớp đã tồn tại" };
    }
    if (error.errorCode === "DuplicateSubjectCode") {
      return { subjectCode: error.message ?? "Mã môn học đã tồn tại" };
    }
    return {};
  }),
}));

import { createClass, createSubject } from "@/lib/reference-api";
import { toast } from "sonner";

/** FR-03 / AC-03d / AC-03e — class and subject reference form */
describe("ClassSubjectForm (AC-03, FR-03)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigateMock.mockReset();
  });

  function renderForm() {
    return render(
      <MemoryRouter>
        <ClassSubjectForm />
      </MemoryRouter>,
    );
  }

  function fillValidForm() {
    fireEvent.change(screen.getByLabelText(/^Mã lớp/), {
      target: { value: "HESD-03" },
    });
    fireEvent.change(screen.getByLabelText(/^Tên lớp/), {
      target: { value: "HESD Cohort 03" },
    });
    fireEvent.change(screen.getByLabelText(/^Mã môn/), {
      target: { value: "SWE-102" },
    });
    fireEvent.change(screen.getByLabelText(/^Tên môn/), {
      target: { value: "Software Engineering 102" },
    });
  }

  it("TC-AC-03-019 / TC-FR-03-028: creates class and subject then navigates to rosters", async () => {
    vi.mocked(createClass).mockResolvedValue({
      ok: true,
      data: {
        id: "class-3",
        code: "HESD-03",
        name: "HESD Cohort 03",
        term: null,
      },
    });
    vi.mocked(createSubject).mockResolvedValue({
      ok: true,
      data: {
        id: "subject-102",
        code: "SWE-102",
        name: "Software Engineering 102",
      },
    });

    renderForm();
    fillValidForm();
    fireEvent.click(screen.getByTestId("class-subject-form-submit"));

    await waitFor(() => {
      expect(createClass).toHaveBeenCalledWith({
        code: "HESD-03",
        name: "HESD Cohort 03",
      });
    });
    expect(createSubject).toHaveBeenCalledWith({
      code: "SWE-102",
      name: "Software Engineering 102",
    });
    expect(toast.success).toHaveBeenCalled();
    expect(navigateMock).toHaveBeenCalledWith("/admin/rosters");
  });

  it("TC-AC-03-022 / TC-FR-03-023: duplicate class code shows inline field error", async () => {
    vi.mocked(createClass).mockResolvedValue({
      ok: false,
      status: 422,
      error: {
        errorCode: "DuplicateClassCode",
        message: "Mã lớp đã tồn tại",
      },
    });

    renderForm();
    fillValidForm();
    fireEvent.click(screen.getByTestId("class-subject-form-submit"));

    await waitFor(() => {
      expect(screen.getByText("Mã lớp đã tồn tại")).toBeInTheDocument();
    });
    expect(createSubject).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("TC-AC-03-023 / TC-FR-03-026: duplicate subject code shows inline field error", async () => {
    vi.mocked(createClass).mockResolvedValue({
      ok: true,
      data: {
        id: "class-3",
        code: "HESD-03",
        name: "HESD Cohort 03",
        term: null,
      },
    });
    vi.mocked(createSubject).mockResolvedValue({
      ok: false,
      status: 422,
      error: {
        errorCode: "DuplicateSubjectCode",
        message: "Mã môn học đã tồn tại",
      },
    });

    renderForm();
    fillValidForm();
    fireEvent.click(screen.getByTestId("class-subject-form-submit"));

    await waitFor(() => {
      expect(screen.getByText("Mã môn học đã tồn tại")).toBeInTheDocument();
    });
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
