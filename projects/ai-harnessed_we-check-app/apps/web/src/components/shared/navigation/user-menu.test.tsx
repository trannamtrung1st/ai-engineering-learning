import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { UserRole } from "@wecheck/domain";
import { UserMenu } from "@/components/shared/navigation/user-menu";
import { appCopy, roleLabels } from "@/lib/copy/status-labels";

/** AC-02 / FR-02 / BR-06 / NFR-16 — UserMenu identity panel and logout */
describe("UserMenu (AC-02, FR-02, BR-06, NFR-16)", () => {
  const baseProps = {
    displayName: "Sinh viên Nguyễn Văn A",
    email: "student@example.edu.vn",
    institutionalId: "SV2026001",
    role: UserRole.Student,
    onLogout: vi.fn(),
    defaultOpen: true,
  };

  it("renders trigger with display name and accessible label (TC-FR-02-026)", () => {
    render(<UserMenu {...baseProps} defaultOpen={false} />);
    const trigger = screen.getByTestId("user-menu-trigger");
    expect(trigger).toHaveAttribute(
      "aria-label",
      `Tài khoản ${baseProps.displayName}`,
    );
    expect(trigger).toHaveTextContent(baseProps.displayName);
  });

  it("shows read-only identity panel with email, institutional id, and role (AC-02e)", () => {
    render(<UserMenu {...baseProps} />);
    const email = screen.getByText(baseProps.email);
    expect(email).toHaveAttribute("title", baseProps.email);
    expect(screen.getByText(`Mã: ${baseProps.institutionalId}`)).toBeInTheDocument();
    expect(screen.getByText(roleLabels[UserRole.Student])).toBeInTheDocument();
    expect(screen.getByTestId("user-menu-logout")).toHaveTextContent(appCopy.logout);
  });

  it("invokes onLogout when Đăng xuất is selected (AC-02d, FR-02)", async () => {
    const onLogout = vi.fn().mockResolvedValue(undefined);
    render(<UserMenu {...baseProps} onLogout={onLogout} />);

    fireEvent.click(screen.getByTestId("user-menu-logout"));

    await waitFor(() => {
      expect(onLogout).toHaveBeenCalledTimes(1);
    });
  });

  it("disables logout while handler is in flight", async () => {
    let resolveLogout: () => void = () => {};
    const onLogout = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveLogout = resolve;
        }),
    );
    render(<UserMenu {...baseProps} onLogout={onLogout} />);

    const logoutItem = screen.getByTestId("user-menu-logout");
    fireEvent.click(logoutItem);

    await waitFor(() => {
      expect(logoutItem).toHaveAttribute("aria-busy", "true");
    });

    resolveLogout();
    await waitFor(() => {
      expect(logoutItem).toHaveAttribute("aria-busy", "false");
    });
  });
});
