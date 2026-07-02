import { Outlet, useMatch } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell";
import { SidebarNav } from "../components/layout/SidebarNav";
import { TopContextHeader } from "../components/layout/TopContextHeader";

const staffNav = [
  { to: "/showcase", label: "Design system" },
  { to: "/lecturer/sessions", label: "Buổi học (PG-04)" },
  { to: "/reports/attendance", label: "Báo cáo (PG-13)" },
];

export function StaffLayout() {
  const projectionSession = useMatch("/lecturer/sessions/:sessionId");
  const rosterSession = useMatch("/lecturer/sessions/:sessionId/roster");

  return (
    <AppShell
      compact={Boolean(projectionSession || rosterSession)}
      sidebar={<SidebarNav items={staffNav} />}
      header={
        <TopContextHeader
          eyebrow="Không gian giảng viên"
          title="Điều khiển buổi học"
          meta="LAY-02 · AppShell + SidebarNav + TopContextHeader"
        />
      }
    >
      <Outlet />
    </AppShell>
  );
}
