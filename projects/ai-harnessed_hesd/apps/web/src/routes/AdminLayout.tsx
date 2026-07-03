import { useEffect, useMemo, useState } from "react";
import { Outlet } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell";
import { SidebarNav, type SidebarNavItem } from "../components/layout/SidebarNav";
import { TopContextHeader } from "../components/layout/TopContextHeader";
import { fetchCurrentUser } from "../lib/api/me-api";
import { resolveRoleHomePath } from "../lib/auth/auth-gate";
import { isAcademicAdmin } from "../lib/auth/role-guard";

const adminNav: SidebarNavItem[] = [
  { to: "/admin/terms", label: "Thiết lập học kỳ" },
  { to: "/admin/class-sections", label: "Lớp học phần" },
  { to: "/admin/policies", label: "Chính sách điểm danh" },
];

/** RBAC nav gating — omit /admin/* links for roles without AcademicAdmin (TC-UX-COMMON-003). */
function resolveAdminNavItems(roles: string[]): SidebarNavItem[] {
  if (isAcademicAdmin(roles)) {
    return adminNav;
  }

  const homePath = resolveRoleHomePath(roles);
  const homeLabel = roles.includes("Student") ? "Trang chủ" : "Phiên học";
  return [{ to: homePath, label: homeLabel }];
}

export function AdminLayout() {
  const [roles, setRoles] = useState<string[] | null>(null);

  useEffect(() => {
    void (async () => {
      const me = await fetchCurrentUser();
      setRoles(me.ok ? me.roles : []);
    })();
  }, []);

  const navItems = useMemo(() => resolveAdminNavItems(roles ?? []), [roles]);
  const showLogout = roles !== null && !roles.every((role) => role === "Student");

  return (
    <AppShell
      sidebar={<SidebarNav items={navItems} showLogout={showLogout} />}
      header={
        <TopContextHeader
          eyebrow="Quản trị học vụ"
          title="Thiết lập cấu trúc học thuật"
        />
      }
    >
      <Outlet />
    </AppShell>
  );
}
