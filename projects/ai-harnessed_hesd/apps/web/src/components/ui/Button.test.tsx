import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "./Button";

describe("Button (FR-14 design tokens)", () => {
  it("renders brand variant with accessible label", () => {
    render(<Button>Mở điểm danh</Button>);
    expect(screen.getByRole("button", { name: "Mở điểm danh" })).toBeEnabled();
  });

  it("marks disabled state", () => {
    render(<Button disabled>Disabled</Button>);
    expect(screen.getByRole("button", { name: "Disabled" })).toBeDisabled();
  });
});
