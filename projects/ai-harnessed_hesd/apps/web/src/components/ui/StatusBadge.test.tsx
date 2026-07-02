import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SessionStatusBadge } from "./StatusBadge";

describe("StatusBadge (NFR-15 state feedback)", () => {
  it("renders Open session badge in Vietnamese", () => {
    render(<SessionStatusBadge state="Open" />);
    expect(screen.getByText("Đang mở")).toBeInTheDocument();
  });

  it("renders Closed session badge", () => {
    render(<SessionStatusBadge state="Closed" />);
    expect(screen.getByText("Đã đóng")).toBeInTheDocument();
  });
});
