import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { GpsCaptureStep } from "@/components/domain/check-in/gps-capture-step";

/** AC-08f / NFR-17 / NFR-18 — GPS ready substate without spinner */
describe("GpsCaptureStep (AC-08f)", () => {
  it("shows check icon and Vị trí đã sẵn sàng without spinner when ready", () => {
    render(<GpsCaptureStep state="ready" />);

    expect(screen.getByText("Vị trí đã sẵn sàng")).toBeInTheDocument();
    expect(screen.getByTestId("gps-ready-icon")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByTestId("gps-capture-step")).toHaveAttribute("aria-busy", "false");
  });

  it("shows spinner during requesting, acquiring, and submitting", () => {
    const { rerender } = render(<GpsCaptureStep state="requesting" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByTestId("gps-capture-step")).toHaveAttribute("aria-busy", "true");

    rerender(<GpsCaptureStep state="acquiring" />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    rerender(<GpsCaptureStep state="submitting" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows denied copy without spinner", () => {
    render(<GpsCaptureStep state="denied" />);

    expect(screen.getByText("Không thể truy cập vị trí")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByTestId("gps-capture-step")).toHaveAttribute("aria-busy", "false");
  });
});
