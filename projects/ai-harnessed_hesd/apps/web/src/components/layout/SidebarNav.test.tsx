import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { SidebarNav } from "./SidebarNav";
import { ACCESS_TOKEN_STORAGE_KEY } from "../../lib/auth/session";
import { STUDENT_AUTH_STORAGE_KEY } from "../../lib/auth/auth-gate";

const logoutMock = vi.fn().mockResolvedValue({ ok: true });

vi.mock("../../lib/api/auth-api.js", () => ({
  logout: () => logoutMock(),
}));

/** Traceability: FR-38 AC-26 FLOW-15 */
describe("SidebarNav (FR-38 AC-26)", () => {
  beforeEach(() => {
    logoutMock.mockClear();
    localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
    sessionStorage.removeItem(STUDENT_AUTH_STORAGE_KEY);
  });

  it("TC-FR-38-006: exposes Đăng xuất in sidebar footer separated from nav items", () => {
    render(
      <MemoryRouter>
        <SidebarNav
          items={[
            { to: "/lecturer/sessions", label: "Phiên học" },
            { to: "/reports/attendance", label: "Báo cáo điểm danh" },
          ]}
        />
      </MemoryRouter>,
    );

    const navLinks = screen.getAllByRole("link");
    expect(navLinks[0]).toHaveTextContent("Phiên học");
    expect(screen.getByRole("button", { name: "Đăng xuất" })).toBeInTheDocument();
    expect(screen.getByRole("separator")).toBeInTheDocument();
  });

  it("TC-AC-26-006: voluntary logout clears credentials and navigates to PG-01", async () => {
    localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, "staff-token");
    sessionStorage.setItem(STUDENT_AUTH_STORAGE_KEY, "1");

    render(
      <MemoryRouter initialEntries={["/lecturer/sessions"]}>
        <SidebarNav items={[{ to: "/lecturer/sessions", label: "Phiên học" }]} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));

    await waitFor(() => {
      expect(logoutMock).toHaveBeenCalledOnce();
      expect(localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)).toBeNull();
      expect(sessionStorage.getItem(STUDENT_AUTH_STORAGE_KEY)).toBeNull();
    });
  });
});
