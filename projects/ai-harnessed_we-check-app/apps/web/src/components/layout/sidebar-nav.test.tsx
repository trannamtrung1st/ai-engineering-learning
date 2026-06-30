import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Calendar } from "lucide-react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { UserRole } from "@wecheck/domain";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import type { AuthOutletContext } from "@/components/auth/require-auth";
import {
  filterPermittedNav,
  getRolePermissions,
  Permission,
} from "@/lib/permissions";

const instructorAuth: AuthOutletContext = {
  user: {
    id: "instructor-1",
    institutionalId: "GV001",
    displayName: "Giảng viên thử",
    email: "instructor@example.edu.vn",
    role: UserRole.Instructor,
  },
};

const adminAuth: AuthOutletContext = {
  user: {
    id: "admin-1",
    institutionalId: "ADMIN001",
    displayName: "Quản trị thử",
    email: "admin@example.edu.vn",
    role: UserRole.TrainingOfficeAdmin,
  },
};

function renderSidebar(
  layout: "instructor" | "admin",
  authUser: AuthOutletContext,
  path = layout === "admin" ? "/admin" : "/sessions",
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="*" element={<Outlet context={authUser} />}>
            <Route
              path="*"
              element={
                <SidebarNav
                  layout={layout}
                  icons={{ "/sessions": Calendar }}
                  testId={`${layout}-sidebar`}
                />
              }
            />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** AC-18 / FR-18 / BR-14 / NFR-11 — permission-gated sidebar nav */
describe("SidebarNav (AC-18, FR-18, BR-14, NFR-11)", () => {
  it("TC-AC-18-002: filterPermittedNav omits unauthorized nav descriptors", () => {
    const sessionOnly = [Permission.SessionRead];
    const instructorNav = filterPermittedNav("instructor", sessionOnly);
    expect(instructorNav.map((item) => item.to)).toEqual(["/sessions"]);
    expect(instructorNav.some((item) => item.to === "/reports")).toBe(false);

    const adminNav = filterPermittedNav("admin", getRolePermissions(UserRole.TrainingOfficeAdmin));
    expect(adminNav.map((item) => item.to)).toEqual([
      "/admin",
      "/admin/users",
      "/admin/rosters",
      "/admin/reports",
      "/admin/export",
      "/admin/policy",
    ]);

    const studentNav = filterPermittedNav("student", getRolePermissions(UserRole.Student));
    expect(studentNav.map((item) => item.to)).toEqual(["/check-in", "/history"]);
    expect(studentNav.some((item) => item.to.startsWith("/admin"))).toBe(false);
  });

  it("TC-AC-18-007: Instructor without report:read omits Báo cáo from sidebar", () => {
    const sessionOnly = [Permission.SessionRead];
    const nav = filterPermittedNav("instructor", sessionOnly);
    expect(nav).toHaveLength(1);
    expect(nav[0]?.label).toBe("Buổi học");
  });

  it("TC-NFR-11-021: instructor SidebarNav renders zero /admin links", () => {
    renderSidebar("instructor", instructorAuth);
    const links = screen.getAllByRole("link");
    for (const link of links) {
      expect(link.getAttribute("href")).not.toMatch(/^\/admin/);
    }
    expect(screen.getByRole("link", { name: /Buổi học/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Báo cáo/ })).toBeInTheDocument();
  });

  it("TC-NFR-11-022: admin SidebarNav includes admin items only", () => {
    renderSidebar("admin", adminAuth);
    expect(screen.getByRole("link", { name: /Trang chủ/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Người dùng/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Điểm danh/ })).not.toBeInTheDocument();
  });

  it("TC-BR-14-006: admin without policy:write omits Chính sách nav item", () => {
    const withoutPolicy = getRolePermissions(UserRole.TrainingOfficeAdmin).filter(
      (p) => p !== Permission.PolicyWrite,
    );
    const nav = filterPermittedNav("admin", withoutPolicy);
    expect(nav.some((item) => item.to === "/admin/policy")).toBe(false);
    expect(nav.some((item) => item.to === "/admin/users")).toBe(true);
  });
});
