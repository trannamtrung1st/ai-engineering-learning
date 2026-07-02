import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ChevronDown, LogOut, User } from "lucide-react";
import { useState } from "react";
import { appCopy, roleLabels } from "@/lib/copy/status-labels";
import type { UserRole } from "@wecheck/domain";
import { cn } from "@/lib/cn";

export interface UserMenuProps {
  displayName: string;
  email: string;
  institutionalId: string;
  role: UserRole;
  onLogout: () => void | Promise<void>;
  isLoggingOut?: boolean;
  /** Opens menu on mount — used by component tests (Radix pointer events in jsdom). */
  defaultOpen?: boolean;
  className?: string;
}

export function UserMenu({
  displayName,
  email,
  institutionalId,
  role,
  onLogout,
  isLoggingOut = false,
  defaultOpen = false,
  className,
}: UserMenuProps) {
  const [busy, setBusy] = useState(false);
  const loggingOut = isLoggingOut || busy;

  async function handleLogout() {
    if (loggingOut) return;
    setBusy(true);
    try {
      await onLogout();
    } finally {
      setBusy(false);
    }
  }

  return (
    <DropdownMenu.Root defaultOpen={defaultOpen}>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          data-testid="user-menu-trigger"
          aria-label={`Tài khoản ${displayName}`}
          className={cn(
            "inline-flex min-h-touch items-center gap-2 rounded-md px-3 py-2 text-body text-text-primary hover:bg-primary-50",
            className,
          )}
        >
          <User className="h-5 w-5" aria-hidden="true" />
          <span className="max-w-[10rem] truncate">{displayName}</span>
          <ChevronDown className="h-4 w-4" aria-hidden="true" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          className="z-dropdown min-w-[14rem] rounded-md border border-border bg-surface-raised p-1 shadow-md"
        >
          <div className="px-3 py-2">
            <p className="font-semibold text-body text-text-primary">{displayName}</p>
            <p className="truncate text-small text-text-secondary" title={email}>
              {email}
            </p>
            <p className="text-small text-text-secondary">Mã: {institutionalId}</p>
            <p className="mt-1 text-small text-text-secondary">{roleLabels[role]}</p>
          </div>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item
            data-testid="user-menu-logout"
            className="flex min-h-touch cursor-pointer items-center gap-2 rounded-sm px-3 text-body outline-none hover:bg-primary-50 data-[disabled]:opacity-60"
            disabled={loggingOut}
            aria-busy={loggingOut}
            onSelect={(event) => {
              event.preventDefault();
              void handleLogout();
            }}
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            {appCopy.logout}
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
