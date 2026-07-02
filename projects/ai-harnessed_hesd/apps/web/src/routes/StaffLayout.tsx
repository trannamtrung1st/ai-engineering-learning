import { Outlet, useMatch } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell";
import { SidebarNav } from "../components/layout/SidebarNav";
import { TopContextHeader } from "../components/layout/TopContextHeader";

const staffNav = [
  { to: "/showcase", label: "Design system" },
  { to: "/lecturer/sessions/demo-open", label: "Buổi học (mở)" },
  { to: "/lecturer/sessions/demo-closed", label: "Buổi học (đóng)" },
];

export function StaffLayout() {
  const projectionSession = useMatch("/lecturer/sessions/:sessionId");

  return (
    <AppShell
      compact={Boolean(projectionSession)}
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
