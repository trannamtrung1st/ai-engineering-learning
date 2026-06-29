import { UserRole } from "@wecheck/domain";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UserForm } from "@/components/admin/user-form";

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

vi.mock("@/lib/users-api", () => ({
  createUser: vi.fn(),
  updateUser: vi.fn(),
  checkUserFieldDuplicate: vi.fn(),
  mapApiDetailsToFieldErrors: vi.fn((details?: { field: string; message: string }[]) => {
    if (!details?.length) return {};
    return Object.fromEntries(details.map((d) => [d.field, d.message]));
  }),
}));

import { createUser, checkUserFieldDuplicate } from "@/lib/users-api";
import { toast } from "sonner";

/** FR-01 / AC-01 — admin user provisioning form */
describe("UserForm (FR-01, AC-01)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigateMock.mockReset();
    vi.mocked(checkUserFieldDuplicate).mockResolvedValue(null);
  });

  function renderForm(mode: "create" | "edit" = "create") {
    return render(
      <MemoryRouter>
        <UserForm mode={mode} />
      </MemoryRouter>,
    );
  }

  it("TC-AC-01-009 / TC-FR-01-009: creates student and navigates to user list", async () => {
    vi.mocked(createUser).mockResolvedValue({
      ok: true,
      data: {
        id: "new-user-id",
        institutionalId: "SV2026999",
        displayName: "Nguyễn Văn Test",
        email: "sv2026999@example.edu.vn",
        role: UserRole.Student,
        active: true,
        createdAt: "2026-06-29T00:00:00.000Z",
      },
    });

    renderForm();

    fireEvent.change(screen.getByLabelText(/Mã SV/), {
      target: { value: "SV2026999" },
    });
    fireEvent.change(screen.getByLabelText(/Họ và tên/), {
      target: { value: "Nguyễn Văn Test" },
    });
    fireEvent.change(screen.getByLabelText(/^Email/), {
      target: { value: "sv2026999@example.edu.vn" },
    });
    fireEvent.change(screen.getByLabelText(/Mật khẩu/), {
      target: { value: "password123" },
    });
    fireEvent.change(screen.getByLabelText(/Vai trò/), {
      target: { value: UserRole.Student },
    });

    fireEvent.click(screen.getByTestId("user-form-submit"));

    await waitFor(() => {
      expect(createUser).toHaveBeenCalledWith(
        expect.objectContaining({
          institutionalId: "SV2026999",
          displayName: "Nguyễn Văn Test",
          email: "sv2026999@example.edu.vn",
          role: UserRole.Student,
        }),
      );
    });
    expect(toast.success).toHaveBeenCalled();
    expect(navigateMock).toHaveBeenCalledWith("/admin/users");
  });

  it("TC-AC-01-010 / TC-FR-01-010: duplicate institutionalId shows inline field error", async () => {
    vi.mocked(createUser).mockResolvedValue({
      ok: false,
      status: 422,
      error: {
        errorCode: "ValidationFailed",
        message: "Dữ liệu không hợp lệ",
        details: [
          {
            field: "institutionalId",
            code: "ValidationFailed",
            message: "Mã định danh đã tồn tại",
          },
        ],
      },
    });

    renderForm();

    fireEvent.change(screen.getByLabelText(/Mã SV/), {
      target: { value: "SV2026001" },
    });
    fireEvent.change(screen.getByLabelText(/Họ và tên/), {
      target: { value: "Trùng mã" },
    });
    fireEvent.change(screen.getByLabelText(/^Email/), {
      target: { value: "dup@example.edu.vn" },
    });
    fireEvent.change(screen.getByLabelText(/Mật khẩu/), {
      target: { value: "password123" },
    });

    fireEvent.click(screen.getByTestId("user-form-submit"));

    await waitFor(() => {
      expect(screen.getByText("Mã định danh đã tồn tại")).toBeInTheDocument();
    });
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("TC-FR-01-009: admin role change requires confirm dialog", async () => {
    renderForm();

    fireEvent.change(screen.getByLabelText(/Mã SV/), {
      target: { value: "ADMIN999" },
    });
    fireEvent.change(screen.getByLabelText(/Họ và tên/), {
      target: { value: "Admin Mới" },
    });
    fireEvent.change(screen.getByLabelText(/^Email/), {
      target: { value: "admin999@example.edu.vn" },
    });
    fireEvent.change(screen.getByLabelText(/Mật khẩu/), {
      target: { value: "password123" },
    });
    fireEvent.change(screen.getByLabelText(/Vai trò/), {
      target: { value: UserRole.TrainingOfficeAdmin },
    });

    fireEvent.click(screen.getByTestId("user-form-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("admin-role-confirm-dialog")).toBeInTheDocument();
    });
    expect(createUser).not.toHaveBeenCalled();
  });
});
