import { History, QrCode } from "lucide-react";
import { Outlet, useLocation, useOutletContext } from "react-router-dom";
import { UserRole } from "@wecheck/domain";
import { AppHeader } from "@/components/layout/app-header";
import { BottomNav } from "@/components/layout/bottom-nav";
import { PageContent } from "@/components/layout/page-content";
import { type AuthOutletContext } from "@/components/auth/require-auth";
import { NotificationBell } from "@/components/notifications/notification-bell";
import { logoutAuth } from "@/lib/auth-session";

const studentNavIcons = {
  "/check-in": QrCode,
  "/history": History,
} as const;

export interface StudentLayoutProps {
  displayName?: string;
  hideBottomNav?: boolean;
}

export interface StudentShellProps {
  displayName: string;
  email: string;
  institutionalId: string;
  onLogout: () => void | Promise<void>;
  hideBottomNav?: boolean;
  pathname?: string;
  children: React.ReactNode;
}

/** AC-18b — student chrome reusable for route outlets and cross-role forbidden pages */
export function StudentShell({
  displayName,
  email,
  institutionalId,
  onLogout,
  hideBottomNav = false,
  pathname = "",
  children,
}: StudentShellProps) {
  const suppressNav = hideBottomNav || pathname.startsWith("/check-in/scan");

  return (
    <div className="flex min-h-screen flex-col bg-surface" data-testid="student-layout">
      <AppHeader
        homeTo="/check-in"
        compact
        user={{
          displayName,
          email,
          institutionalId,
          role: UserRole.Student,
          onLogout,
        }}
        headerActions={<NotificationBell />}
      />
      <main id="main-content" className="flex-1">
        <PageContent variant="narrow">{children}</PageContent>
      </main>
      {!suppressNav ? <BottomNav icons={studentNavIcons} /> : null}
    </div>
  );
}

export function StudentLayout({
  hideBottomNav = false,
}: Omit<StudentLayoutProps, "displayName">) {
  const authContext = useOutletContext<AuthOutletContext>();
  const location = useLocation();

  return (
    <StudentShell
      displayName={authContext.user.displayName}
      email={authContext.user.email}
      institutionalId={authContext.user.institutionalId}
      onLogout={logoutAuth}
      hideBottomNav={hideBottomNav}
      pathname={location.pathname}
    >
      <Outlet context={authContext} />
    </StudentShell>
  );
}
