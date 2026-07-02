import { Outlet } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell";
import { SidebarNav } from "../components/layout/SidebarNav";
import { TopContextHeader } from "../components/layout/TopContextHeader";

const adminNav = [
  { to: "/admin/terms", label: "Học kỳ (PG-07)" },
  { to: "/admin/class-sections", label: "Lớp học phần (PG-09)" },
  { to: "/admin/policies", label: "Chính sách (PG-12)" },
];

export function AdminLayout() {
  return (
    <AppShell
      sidebar={<SidebarNav items={adminNav} />}
      header={
        <TopContextHeader
          eyebrow="Quản trị học vụ"
          title="Thiết lập cấu trúc học thuật"
          meta="SUR-04 · AcademicAdmin workspace"
        />
      }
    >
      <Outlet />
    </AppShell>
  );
}
