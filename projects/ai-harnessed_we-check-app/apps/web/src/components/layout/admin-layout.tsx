import {
  BarChart3,
  Download,
  Menu,
  Settings,
  Upload,
  Users,
} from "lucide-react";
import { useState } from "react";
import { Outlet } from "react-router-dom";
import { UserRole } from "@wecheck/domain";
import { PageContent } from "@/components/layout/page-content";
import { Breadcrumb } from "@/components/shared/navigation/breadcrumb";
import { NavLink } from "@/components/shared/navigation/nav-link";
import { UserMenu } from "@/components/shared/navigation/user-menu";
import { IconButton } from "@/components/ui/icon-button";
import { adminNavItems, appCopy } from "@/lib/copy/status-labels";
import { cn } from "@/lib/cn";

const navIcons = {
  "/admin/users": Users,
  "/admin/rosters": Upload,
  "/admin/reports": BarChart3,
  "/admin/export": Download,
  "/admin/policy": Settings,
} as const;

export interface AdminLayoutProps {
  displayName?: string;
}

export function AdminLayout({ displayName = "Quản trị viên" }: AdminLayoutProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div
      className="min-h-screen bg-surface lg:grid lg:grid-cols-[240px_1fr]"
      data-testid="admin-layout"
    >
      <aside
        className="hidden border-r border-border bg-surface-raised lg:block"
        aria-label="Điều hướng quản trị"
      >
        <AdminSidebar />
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
            <AdminSidebar onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      ) : null}

      <div className="flex min-h-screen flex-col">
        <header className="sticky top-0 z-sticky flex h-16 items-center justify-between gap-4 border-b border-border bg-surface-raised px-4 lg:px-6">
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
                { label: appCopy.adminSection, to: "/admin/users" },
                { label: "Bảng điều khiển" },
              ]}
            />
          </div>
          <UserMenu displayName={displayName} role={UserRole.TrainingOfficeAdmin} />
        </header>
        <main id="main-content" className="flex-1">
          <PageContent variant="wide">
            <Outlet />
          </PageContent>
        </main>
      </div>
    </div>
  );
}

function AdminSidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border p-4">
        <p className="text-small font-semibold uppercase tracking-wide text-text-secondary">
          {appCopy.adminSection}
        </p>
        <p className="text-h2 font-semibold text-primary-700">{appCopy.productName}</p>
      </div>
      <nav className="flex flex-col gap-1 p-4" data-testid="admin-sidebar">
        {adminNavItems.map((item) => {
          const Icon = navIcons[item.to as keyof typeof navIcons];
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={cn("w-full")}
              {...(onNavigate ? { onClick: onNavigate } : {})}
            >
              <Icon className="h-5 w-5" aria-hidden="true" />
              {item.label}
            </NavLink>
          );
        })}
      </nav>
    </div>
  );
}
