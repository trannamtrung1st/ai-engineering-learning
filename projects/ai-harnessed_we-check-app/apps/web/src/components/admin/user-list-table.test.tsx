import { UserRole } from "@wecheck/domain";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UserListTable } from "@/components/admin/user-list-table";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/users-api", () => ({
  updateUser: vi.fn(),
}));

import { updateUser } from "@/lib/users-api";
import { toast } from "sonner";

const activeStudent = {
  id: "user-1",
  institutionalId: "SV2026001",
  displayName: "Nguyễn Văn A",
  email: "student@example.edu.vn",
  role: UserRole.Student,
  active: true,
  createdAt: "2026-06-01T00:00:00.000Z",
};

const inactiveStudent = {
  ...activeStudent,
  id: "user-2",
  institutionalId: "SV2026002",
  displayName: "Nguyễn Văn B",
  email: "studentb@example.edu.vn",
  active: false,
};

/** FR-01 / AC-01 / NFR-11 — admin user list table */
describe("UserListTable (FR-01, AC-01, NFR-11)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("TC-FR-01-009: renders active badge for active users", () => {
    render(
      <MemoryRouter>
        <UserListTable users={[activeStudent]} />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("user-list-table")).toBeInTheDocument();
    expect(screen.getByTestId("user-row-SV2026001")).toBeInTheDocument();
    expect(screen.getAllByTestId("user-active-badge")[0]).toHaveTextContent("Đang hoạt động");
  });

  it("TC-FR-01-016: deactivates user and shows inactive badge", async () => {
    const onUserUpdated = vi.fn();
    vi.mocked(updateUser).mockResolvedValue({
      ok: true,
      data: { ...activeStudent, active: false },
    });

    const { rerender } = render(
      <MemoryRouter>
        <UserListTable users={[activeStudent]} onUserUpdated={onUserUpdated} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId("deactivate-user-SV2026001"));
    expect(screen.getByTestId("deactivate-user-dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("confirm-dialog-accept"));

    await waitFor(() => {
      expect(updateUser).toHaveBeenCalledWith("user-1", { active: false });
    });
    expect(toast.success).toHaveBeenCalled();
    expect(onUserUpdated).toHaveBeenCalled();

    rerender(
      <MemoryRouter>
        <UserListTable users={[inactiveStudent]} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("user-inactive-badge")).toHaveTextContent("Đã vô hiệu hóa");
  });

  it("NFR-11: table shows institutionalId and email columns", () => {
    render(
      <MemoryRouter>
        <UserListTable users={[activeStudent]} />
      </MemoryRouter>,
    );

    expect(screen.getByText("SV2026001")).toBeInTheDocument();
    expect(screen.getByText("student@example.edu.vn")).toBeInTheDocument();
    expect(screen.getByText("Sinh viên")).toBeInTheDocument();
  });
});
