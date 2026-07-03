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
} from "../lib/auth/role-guard";

const baseStaffNav: SidebarNavItem[] = [
  { to: "/showcase", label: "Design system" },
  { to: "/lecturer/sessions", label: "Buổi học (PG-04)" },
  { to: "/reports/attendance", label: "Báo cáo (PG-13)" },
  { to: "/audit/logs", label: "Audit (PG-15)" },
];

function resolveStaffNavItems(roles: string[]): SidebarNavItem[] {
  return baseStaffNav.filter((item) => {
    if (item.to === "/lecturer/sessions") {
      return canAccessSessionControl(roles);
    }
    if (item.to === "/reports/attendance") {
      return canAccessInstitutionReport(roles);
    }
    if (item.to === "/audit/logs") {
      return canAccessAuditLogs(roles);
    }
    return true;
  });
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
          meta="LAY-02 · AppShell + SidebarNav + TopContextHeader"
        />
      }
    >
      <Outlet />
    </AppShell>
  );
}
