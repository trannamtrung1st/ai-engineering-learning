import {
  BarChart3,
  Download,
  Home,
  Menu,
  Settings,
  Upload,
  Users,
} from "lucide-react";
import { useState } from "react";
import { Outlet, useLocation, useOutletContext } from "react-router-dom";
import { UserRole } from "@wecheck/domain";
import { PageContent } from "@/components/layout/page-content";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { Breadcrumb } from "@/components/shared/navigation/breadcrumb";
import { UserMenu } from "@/components/shared/navigation/user-menu";
import { IconButton } from "@/components/ui/icon-button";
import { type AuthOutletContext } from "@/components/auth/require-auth";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { StudentShell } from "@/components/layout/student-layout";
import { getRoleHome } from "@/lib/auth-redirect";
import {
  canAccessAdminShell,
  getAdminForbiddenDescription,
} from "@/lib/admin-route-access";
import { appCopy } from "@/lib/copy/status-labels";

const adminNavIcons = {
  "/admin": Home,
  "/admin/users": Users,
  "/admin/rosters": Upload,
  "/admin/reports": BarChart3,
  "/admin/export": Download,
  "/admin/policy": Settings,
} as const;

export interface AdminLayoutProps {
  displayName?: string;
}

export function AdminLayout() {
  const authContext = useOutletContext<AuthOutletContext>();
  const user = authContext.user;
  const { pathname } = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);

  if (!canAccessAdminShell(user.role, pathname)) {
    if (user.role === UserRole.Student) {
      return (
        <StudentShell displayName={user.displayName} pathname={pathname}>
          <ForbiddenPage homeTo={getRoleHome(user.role)} />
        </StudentShell>
      );
    }

    return (
      <ForbiddenPage
        homeTo={getRoleHome(user.role)}
        description={getAdminForbiddenDescription(pathname)}
      />
    );
  }

  const isInstructorRosterShell =
    user.role === UserRole.Instructor && canAccessAdminShell(user.role, pathname);

  if (isInstructorRosterShell) {
    return (
      <div
        className="min-h-screen bg-surface"
        data-testid="admin-roster-shell"
      >
        <header className="sticky top-0 z-sticky flex h-16 items-center justify-between gap-4 border-b border-border bg-surface-raised px-4 shadow-sm lg:px-6">
          <Breadcrumb
            items={[
              { label: "Buổi học", to: "/sessions" },
              { label: "Danh sách lớp" },
            ]}
          />
          <UserMenu displayName={user.displayName} role={UserRole.Instructor} />
        </header>
        <main id="main-content" className="flex-1">
          <PageContent variant="wide">
            <Outlet context={authContext} />
          </PageContent>
        </main>
      </div>
    );
  }

  const sidebarHeader = (
    <div className="border-b border-border p-4 pl-5">
      <p className="text-small font-semibold uppercase tracking-wide text-text-secondary">
        {appCopy.adminSection}
      </p>
      <p className="font-display text-h2 font-semibold text-brand-700">
        {appCopy.productName}
      </p>
    </div>
  );

  return (
    <div
      className="min-h-screen bg-surface lg:grid lg:grid-cols-[240px_1fr]"
      data-testid="admin-layout"
    >
      <aside
        className="relative hidden border-r border-border bg-surface-raised lg:block"
        aria-label="Điều hướng quản trị"
      >
        <div
          className="absolute inset-y-0 left-0 w-1 bg-brand-700"
          aria-hidden="true"
        />
        <SidebarNav layout="admin" icons={adminNavIcons} header={sidebarHeader} />
      </aside>

      {drawerOpen ? (
        <div className="fixed inset-0 z-modal lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-surface-inverse/40"
            aria-label="Đóng menu"
            onClick={() => setDrawerOpen(false)}
          />
          <aside className="relative h-full w-64 bg-surface-raised p-4 shadow-lg">
            <div
              className="absolute inset-y-0 left-0 w-1 bg-brand-700"
              aria-hidden="true"
            />
            <SidebarNav
              layout="admin"
              icons={adminNavIcons}
              header={sidebarHeader}
              onNavigate={() => setDrawerOpen(false)}
            />
          </aside>
        </div>
      ) : null}

      <div className="flex min-h-screen flex-col">
        <header className="sticky top-0 z-sticky flex h-16 items-center justify-between gap-4 border-b border-border bg-surface-raised px-4 shadow-sm lg:px-6">
          <div className="flex items-center gap-3">
            <IconButton
              className="lg:hidden"
              aria-label="Mở menu"
              onClick={() => setDrawerOpen(true)}
            >
              <Menu className="h-5 w-5" />
            </IconButton>
            <Breadcrumb
              items={[
                { label: appCopy.adminSection, to: "/admin" },
                { label: "Bảng điều khiển" },
              ]}
            />
          </div>
          <UserMenu displayName={user.displayName} role={UserRole.TrainingOfficeAdmin} />
        </header>
        <main id="main-content" className="flex-1">
          <PageContent variant="wide">
            <Outlet context={authContext} />
          </PageContent>
        </main>
      </div>
    </div>
  );
}
