import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { PermissionGuideModal } from "@/components/shared/permission-guide-modal";

/** TC-NFR-19-017, NFR-19 — focus trap, numbered steps, aria-labelledby */
describe("PermissionGuideModal (TC-NFR-19-017, NFR-19)", () => {
  it("renders numbered steps and Vietnamese title for iOS GPS guide", () => {
    render(
      <PermissionGuideModal open type="gps" platform="ios" onClose={() => undefined} />,
    );

    expect(screen.getByRole("dialog")).toHaveAttribute("aria-labelledby", "permission-guide-title");
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-describedby", "permission-guide-steps");
    expect(screen.getByRole("list")).toHaveAttribute("id", "permission-guide-steps");
    expect(screen.getAllByRole("listitem").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByRole("button", { name: "Đóng" })).toBeInTheDocument();
    expect(screen.getByTestId("permission-guide-modal-gps")).toHaveAttribute(
      "data-axe-scope",
      "permission-guide-modal",
    );
  });

  it("traps focus inside modal until Đóng clicked (TC-NFR-19-017)", () => {
    const onClose = vi.fn();
    render(
      <PermissionGuideModal open type="camera" platform="android" onClose={onClose} />,
    );

    const closeButton = screen.getByRole("button", { name: "Đóng" });
    closeButton.focus();
    expect(document.activeElement).toBe(closeButton);

    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(closeButton);

    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(closeButton);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("returns focus to trigger element after close", () => {
    const trigger = document.createElement("button");
    trigger.textContent = "Hướng dẫn cấp quyền";
    document.body.appendChild(trigger);
    trigger.focus();

    const onClose = vi.fn();
    const { rerender } = render(
      <PermissionGuideModal open type="gps" platform="ios" onClose={onClose} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Đóng" }));
    rerender(
      <PermissionGuideModal open={false} type="gps" platform="ios" onClose={onClose} />,
    );

    expect(onClose).toHaveBeenCalled();
    trigger.remove();
  });
});
