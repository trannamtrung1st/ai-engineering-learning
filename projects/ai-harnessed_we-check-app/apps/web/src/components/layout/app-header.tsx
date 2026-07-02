import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { appCopy } from "@/lib/copy/status-labels";
import { UserMenu, type UserMenuProps } from "@/components/shared/navigation/user-menu";
import { cn } from "@/lib/cn";

export interface AppHeaderProps {
  homeTo?: string;
  compact?: boolean;
  user?: Pick<
    UserMenuProps,
    "displayName" | "email" | "institutionalId" | "role" | "onLogout"
  >;
  headerActions?: ReactNode;
  className?: string;
}

export function AppHeader({
  homeTo = "/check-in",
  compact = false,
  user,
  headerActions,
  className,
}: AppHeaderProps) {
  return (
    <header
      className={cn(
        "sticky top-0 z-sticky flex h-14 items-center justify-between border-b border-border bg-surface-raised px-4",
        compact && "h-14",
        className,
      )}
    >
      <Link
        to={homeTo}
        className="text-h2 font-semibold text-primary-700"
        data-testid="app-logo"
      >
        {appCopy.productName}
      </Link>
      {user ? (
        <div className="flex items-center gap-2">
          {headerActions}
          <UserMenu
            displayName={user.displayName}
            email={user.email}
            institutionalId={user.institutionalId}
            role={user.role}
            onLogout={user.onLogout}
          />
        </div>
      ) : null}
    </header>
  );
}
