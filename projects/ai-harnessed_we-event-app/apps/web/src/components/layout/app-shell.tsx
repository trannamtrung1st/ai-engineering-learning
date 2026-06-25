import { type ReactNode } from "react";

import { type AppRole, type NavItem } from "@/lib/app-context";
import { cn } from "@/lib/cn";

import { MainContentFrame } from "./main-content-frame";
import { SideNav } from "./side-nav";
import { TopBar } from "./top-bar";

export interface AppShellProps {
  role: AppRole;
  children: ReactNode;
  navItems?: NavItem[];
  organizationName?: string;
  userDisplayName?: string;
  aside?: ReactNode;
  className?: string;
}

export function AppShell({
  role,
  children,
  navItems = [],
  organizationName,
  userDisplayName,
  aside,
  className,
}: AppShellProps) {
  const showSideNav = role !== "participant" && navItems.length > 0;

  return (
    <div className={cn("flex min-h-dvh flex-col bg-[var(--color-bg-default)]", className)}>
      <TopBar
        role={role}
        organizationName={organizationName}
        userDisplayName={userDisplayName}
      />
      <div className="flex flex-1 flex-col lg:flex-row">
        {showSideNav ? <SideNav items={navItems} role={role} /> : null}
        <main className="flex min-w-0 flex-1 flex-col">
          <MainContentFrame aside={aside}>{children}</MainContentFrame>
        </main>
      </div>
    </div>
  );
}
