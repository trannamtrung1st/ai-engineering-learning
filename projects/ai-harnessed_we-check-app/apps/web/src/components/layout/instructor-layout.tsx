import { BarChart3, Calendar, Menu } from "lucide-react";
import { useState } from "react";
import { Outlet } from "react-router-dom";
import { UserRole } from "@wecheck/domain";
import { PageContent } from "@/components/layout/page-content";
import {
  Breadcrumb,
  type BreadcrumbItem,
} from "@/components/shared/navigation/breadcrumb";
import { NavLink } from "@/components/shared/navigation/nav-link";
import { UserMenu } from "@/components/shared/navigation/user-menu";
import { IconButton } from "@/components/ui/icon-button";
import { useAuthUser } from "@/components/auth/require-auth";
import { instructorNavItems } from "@/lib/copy/status-labels";
import { cn } from "@/lib/cn";

const navIcons = {
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
  const user = useAuthUser();
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div
      className="min-h-screen bg-surface lg:grid lg:grid-cols-[240px_1fr]"
      data-testid="instructor-layout"
    >
      <aside
        className="hidden border-r border-border bg-surface-raised lg:block"
        aria-label="Điều hướng giảng viên"
      >
        <SidebarNav />
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
            <SidebarNav onNavigate={() => setDrawerOpen(false)} />
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
            <Breadcrumb items={breadcrumbs} />
          </div>
          <UserMenu displayName={user.displayName} role={UserRole.Instructor} />
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

function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-col gap-1 p-4" data-testid="instructor-sidebar">
      {instructorNavItems.map((item) => {
        const Icon = navIcons[item.to as keyof typeof navIcons];
        return (
          <NavLink
            key={item.to}
            to={item.to}
            className={cn("w-full")}
            {...(onNavigate
              ? { onClick: onNavigate }
              : {})}
          >
            <Icon className="h-5 w-5" aria-hidden="true" />
            {item.label}
          </NavLink>
        );
      })}
    </nav>
  );
}
