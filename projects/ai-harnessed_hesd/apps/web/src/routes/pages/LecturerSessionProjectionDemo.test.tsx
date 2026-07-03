import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { LecturerSessionProjectionDemo } from "./LecturerSessionProjectionDemo";

/** Traceability: NFR-15 FR-14 */
describe("LecturerSessionProjectionDemo (NFR-15)", () => {
  it("TC-NFR-15-010: demo-open renders PG-05 projection QR without auth", () => {
    render(
      <MemoryRouter>
        <LecturerSessionProjectionDemo sessionId="demo-open" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Mã QR điểm danh" })).toBeInTheDocument();
    expect(screen.getByText("CSE101-A")).toBeInTheDocument();
    expect(screen.getByText(/Lập trình Web.*Buổi 05/)).toBeInTheDocument();
    expect(screen.getByTestId("qr-display-canvas")).toBeInTheDocument();
  });

  it("TC-NFR-15-011: demo-closed hides QR canvas and shows locked copy", () => {
    render(
      <MemoryRouter>
        <LecturerSessionProjectionDemo sessionId="demo-closed" />
      </MemoryRouter>,
    );

    expect(screen.queryByTestId("qr-display-canvas")).not.toBeInTheDocument();
    expect(screen.getByText(/Buổi học đã đóng.*mã QR không còn hiệu lực/)).toBeInTheDocument();
  });
});
