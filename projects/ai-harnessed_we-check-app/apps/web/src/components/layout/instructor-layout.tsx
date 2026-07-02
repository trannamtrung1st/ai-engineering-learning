import { BarChart3, Calendar, Menu } from "lucide-react";
import { useState } from "react";
import { Outlet, useOutletContext } from "react-router-dom";
import { UserRole } from "@wecheck/domain";
import { PageContent } from "@/components/layout/page-content";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import {
  Breadcrumb,
  type BreadcrumbItem,
} from "@/components/shared/navigation/breadcrumb";
import { UserMenu } from "@/components/shared/navigation/user-menu";
import { IconButton } from "@/components/ui/icon-button";
import { type AuthOutletContext } from "@/components/auth/require-auth";
import { NotificationBell } from "@/components/notifications/notification-bell";
import { logoutAuth } from "@/lib/auth-session";

const instructorNavIcons = {
  "/sessions": Calendar,
  "/reports": BarChart3,
} as const;

export interface InstructorLayoutProps {
  displayName?: string;
  breadcrumbs?: BreadcrumbItem[];
}

export function InstructorLayout({
  breadcrumbs = [{ label: "Buổi học", to: "/sessions" }],
}: Omit<InstructorLayoutProps, "displayName">) {
  const authContext = useOutletContext<AuthOutletContext>();
  const user = authContext.user;
  const [drawerOpen, setDrawerOpen] = useState(false);

  const sidebarHeader = (
    <div className="mb-4 border-b border-border pb-4">
      <p className="font-display text-h2 font-semibold text-brand-700">We Check</p>
      <p className="text-small text-text-secondary">Giảng viên</p>
    </div>
  );

  return (
    <div
      className="min-h-screen bg-surface lg:grid lg:grid-cols-[240px_1fr]"
      data-testid="instructor-layout"
    >
      <aside
        className="relative hidden border-r border-border bg-surface-raised lg:block"
        aria-label="Điều hướng giảng viên"
      >
        <div
          className="absolute inset-y-0 left-0 w-1 bg-brand-700"
          aria-hidden="true"
        />
        <SidebarNav layout="instructor" icons={instructorNavIcons} header={sidebarHeader} />
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
              layout="instructor"
              icons={instructorNavIcons}
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
            <Breadcrumb items={breadcrumbs} />
          </div>
          <div className="flex items-center gap-2">
            <NotificationBell />
            <UserMenu
              displayName={user.displayName}
              email={user.email}
              institutionalId={user.institutionalId}
              role={UserRole.Instructor}
              onLogout={logoutAuth}
            />
          </div>
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
