import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BarChart3, Users } from "lucide-react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { UserRole } from "@wecheck/domain";
import { RoleHomeHub } from "@/components/layout/role-home-hub";
import type { AuthOutletContext } from "@/components/auth/require-auth";
import {
  filterHubCards,
  getRolePermissions,
  Permission,
} from "@/lib/permissions";

const adminAuth: AuthOutletContext = {
  user: {
    id: "admin-1",
    institutionalId: "ADMIN001",
    displayName: "Quản trị thử",
    email: "admin@example.edu.vn",
    role: UserRole.TrainingOfficeAdmin,
  },
};

const instructorAuth: AuthOutletContext = {
  user: {
    id: "instructor-1",
    institutionalId: "GV001",
    displayName: "Giảng viên thử",
    email: "instructor@example.edu.vn",
    role: UserRole.Instructor,
  },
};

const studentAuth: AuthOutletContext = {
  user: {
    id: "student-1",
    institutionalId: "SV001",
    displayName: "Sinh viên thử",
    email: "student@example.edu.vn",
    role: UserRole.Student,
  },
};

const adminIcons: Record<string, typeof Users> = {
  "/admin/users": Users,
  "/admin/reports": BarChart3,
} as const;

function renderHub(variant: "admin" | "instructor" | "student", authUser: AuthOutletContext) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  const icons: Record<string, typeof Users> =
    variant === "admin"
      ? adminIcons
      : variant === "instructor"
        ? { "/sessions/new": Users, "/reports": BarChart3 }
        : { "/check-in": Users, "/history": BarChart3 };

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Routes>
          <Route path="*" element={<Outlet context={authUser} />}>
            <Route
              index
              element={<RoleHomeHub variant={variant} icons={icons} title="Hub" />}
            />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** AC-18 / FR-18 / BR-14 — permission-filtered role home hubs */
describe("RoleHomeHub (AC-18, FR-18, BR-14)", () => {
  it("TC-AC-18-003: filterHubCards returns full admin catalog with all permissions", () => {
    const cards = filterHubCards("admin", getRolePermissions(UserRole.TrainingOfficeAdmin));
    const titles = cards.map((card) => card.title);
    expect(titles).toContain("Quản lý người dùng");
    expect(titles).toContain("Danh sách lớp");
    expect(titles).toContain("Báo cáo");
    expect(titles).toContain("Xuất CSV");
    expect(titles).toContain("Chính sách");
  });

  it("TC-AC-18-003: filterHubCards omits Chính sách when policy:write absent", () => {
    const withoutPolicy = getRolePermissions(UserRole.TrainingOfficeAdmin).filter(
      (p) => p !== Permission.PolicyWrite,
    );
    const cards = filterHubCards("admin", withoutPolicy);
    expect(cards.some((card) => card.title === "Chính sách")).toBe(false);
    expect(cards.some((card) => card.title === "Quản lý người dùng")).toBe(true);
  });

  it("TC-FR-18-003: instructor hub includes session and report cards", () => {
    const cards = filterHubCards("instructor", getRolePermissions(UserRole.Instructor));
    expect(cards.map((c) => c.title)).toEqual(
      expect.arrayContaining(["Tạo buổi học mới", "Báo cáo điểm danh"]),
    );
  });

  it("TC-FR-18-016: student RoleHomeHub renders student quick links", () => {
    renderHub("student", studentAuth);
    expect(screen.getByTestId("student-hub-scan")).toHaveAttribute("href", "/check-in");
    expect(screen.getByTestId("student-hub-history")).toHaveAttribute("href", "/history");
  });

  it("TC-FR-18-016: student hub descriptor set excludes admin routes", () => {
    const cards = filterHubCards("student", getRolePermissions(UserRole.Student));
    expect(cards.map((c) => c.to)).toEqual(["/check-in", "/history"]);
    expect(cards.some((c) => c.to.startsWith("/admin"))).toBe(false);
  });

  it("TC-AC-18-012: instructor RoleHomeHub renders permitted workflow links", () => {
    renderHub("instructor", instructorAuth);
    expect(screen.getByTestId("role-home-hub")).toBeInTheDocument();
    expect(screen.getByTestId("instructor-hub-create-session")).toHaveAttribute(
      "href",
      "/sessions/new",
    );
    expect(screen.getByTestId("instructor-hub-reports")).toHaveAttribute("href", "/reports");
  });

  it("TC-AC-18-008: admin RoleHomeHub renders NavCard deep links", () => {
    renderHub("admin", adminAuth);
    expect(screen.getByTestId("admin-hub-users")).toHaveAttribute("href", "/admin/users");
  });
});
