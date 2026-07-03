import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AttendanceStatusCell } from "./AttendanceStatusCell";

/** Traceability: FR-37 */
describe("AttendanceStatusCell — FR-37", () => {
  it("renders status badge and QR method label", () => {
    render(<AttendanceStatusCell status="Present" method="QR" />);
    expect(screen.getByText("Có mặt")).toBeInTheDocument();
    expect(screen.getByText("QR")).toBeInTheDocument();
  });

  it("maps Admin Correction method to compact label", () => {
    render(<AttendanceStatusCell status="Manual Present" method="Admin Correction" />);
    expect(screen.getByText("Admin")).toBeInTheDocument();
  });
});
