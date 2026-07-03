import { useEffect, useMemo, useState } from "react";
import { Outlet, useMatch } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell";
import { SidebarNav, type SidebarNavItem } from "../components/layout/SidebarNav";
import { TopContextHeader } from "../components/layout/TopContextHeader";
import { fetchCurrentUser } from "../lib/api/me-api";
import {
  canAccessAuditLogs,
  canAccessInstitutionReport,
  canAccessSessionControl,
  resolveStaffHomeNav,
} from "../lib/auth/role-guard";

function resolveStaffNavItems(roles: string[]): SidebarNavItem[] {
  const home = resolveStaffHomeNav(roles);
  const items: SidebarNavItem[] = [home];

  if (home.to !== "/lecturer/sessions" && canAccessSessionControl(roles)) {
    items.push({ to: "/lecturer/sessions", label: "Buổi học" });
  }

  if (canAccessInstitutionReport(roles)) {
    items.push({ to: "/reports/attendance", label: "Báo cáo điểm danh" });
  }

  if (home.to !== "/audit/logs" && canAccessAuditLogs(roles)) {
    items.push({ to: "/audit/logs", label: "Nhật ký kiểm toán" });
  }

  items.push({ to: "/showcase", label: "Design system" });

  return items;
}

export function StaffLayout() {
  const projectionSession = useMatch("/lecturer/sessions/:sessionId");
  const rosterSession = useMatch("/lecturer/sessions/:sessionId/roster");
  const auditRoster = useMatch("/audit/sessions/:sessionId/roster");
  const auditLogs = useMatch("/audit/logs");
  const [roles, setRoles] = useState<string[] | null>(null);

  useEffect(() => {
    void (async () => {
      const me = await fetchCurrentUser();
      setRoles(me.ok ? me.roles : []);
    })();
  }, []);

  const navItems = useMemo(
    () => resolveStaffNavItems(roles ?? []),
    [roles],
  );

  const headerTitle = auditLogs
    ? "Tra cứu nhật ký audit"
    : auditRoster
      ? "Danh sách buổi học (chỉ đọc)"
      : "Điều khiển buổi học";

  const headerEyebrow = auditLogs || auditRoster ? "Không gian kiểm toán" : "Không gian giảng viên";

  return (
    <AppShell
      compact={Boolean(projectionSession || rosterSession || auditRoster)}
      sidebar={<SidebarNav items={navItems} />}
      header={
        <TopContextHeader
          eyebrow={headerEyebrow}
          title={headerTitle}
        />
      }
    >
      <Outlet />
    </AppShell>
  );
}
