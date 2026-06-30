import { History, QrCode } from "lucide-react";
import { Outlet, useLocation, useOutletContext } from "react-router-dom";
import { UserRole } from "@wecheck/domain";
import { AppHeader } from "@/components/layout/app-header";
import { PageContent } from "@/components/layout/page-content";
import { NavLink } from "@/components/shared/navigation/nav-link";
import { type AuthOutletContext } from "@/components/auth/require-auth";
import { NotificationBell } from "@/components/notifications/notification-bell";
import { studentNavItems } from "@/lib/copy/status-labels";

const navIcons = {
  "/check-in": QrCode,
  "/history": History,
} as const;

export interface StudentLayoutProps {
  displayName?: string;
  hideBottomNav?: boolean;
}

export function StudentLayout({
  hideBottomNav = false,
}: Omit<StudentLayoutProps, "displayName">) {
  const authContext = useOutletContext<AuthOutletContext>();
  const user = authContext.user;
  const location = useLocation();
  const suppressNav =
    hideBottomNav || location.pathname.startsWith("/check-in/scan");

  return (
    <div className="flex min-h-screen flex-col bg-surface" data-testid="student-layout">
      <AppHeader
        homeTo="/check-in"
        compact
        user={{
          displayName: user.displayName,
          role: UserRole.Student,
        }}
        headerActions={<NotificationBell />}
      />
      <main id="main-content" className="flex-1">
        <PageContent variant="narrow">
          <Outlet context={authContext} />
        </PageContent>
      </main>
      {!suppressNav ? (
        <nav
          aria-label="Điều hướng sinh viên"
          className="sticky bottom-0 border-t border-border bg-surface-raised/95 pb-[env(safe-area-inset-bottom)] shadow-sm backdrop-blur-sm"
          data-testid="student-bottom-nav"
        >
          <div className="mx-auto flex max-w-[480px] justify-around px-2 py-1">
            {studentNavItems.map((item) => {
              const Icon = navIcons[item.to as keyof typeof navIcons];
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className="flex-1 flex-col gap-1 rounded-full py-2 text-small"
                >
                  <Icon className="h-5 w-5" aria-hidden="true" />
                  {item.label}
                </NavLink>
              );
            })}
          </div>
        </nav>
      ) : null}
    </div>
  );
}
