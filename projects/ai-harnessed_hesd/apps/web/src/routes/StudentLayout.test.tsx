import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { StudentLayout } from "./StudentLayout";
import { ACCESS_TOKEN_STORAGE_KEY } from "../lib/auth/session";
import { STUDENT_AUTH_STORAGE_KEY } from "../lib/auth/auth-gate";

vi.mock("../lib/api/auth-api.js", () => ({
  logout: vi.fn().mockResolvedValue({ ok: true }),
}));

/** Traceability: FR-38 AC-26 FLOW-15 */
describe("StudentLayout (FR-38 AC-26)", () => {
  beforeEach(() => {
    localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
    sessionStorage.removeItem(STUDENT_AUTH_STORAGE_KEY);
  });

  it("TC-FR-38-007: shows header logout when student is authenticated", () => {
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "student-jwt");

    render(
      <MemoryRouter initialEntries={["/check-in"]}>
        <Routes>
          <Route element={<StudentLayout />}>
            <Route path="/check-in" element={<p>Check-in body</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "Trang chủ" })).toHaveAttribute("href", "/check-in");
    expect(screen.getByRole("button", { name: "Đăng xuất" })).toBeInTheDocument();
  });

  it("TC-AC-26-008: hides shell header on PG-01 login", () => {
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "student-jwt");

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route element={<StudentLayout />}>
            <Route path="/login" element={<p>Login body</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.queryByRole("button", { name: "Đăng xuất" })).not.toBeInTheDocument();
    expect(screen.getByText("Login body")).toBeInTheDocument();
  });

  it("hides shell header when unauthenticated", () => {
    render(
      <MemoryRouter initialEntries={["/check-in"]}>
        <Routes>
          <Route element={<StudentLayout />}>
            <Route path="/check-in" element={<p>Check-in body</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.queryByRole("button", { name: "Đăng xuất" })).not.toBeInTheDocument();
  });
});
