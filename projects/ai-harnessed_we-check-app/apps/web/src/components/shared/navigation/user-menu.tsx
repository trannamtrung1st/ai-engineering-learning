import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ChevronDown, LogOut, User } from "lucide-react";
import { appCopy, roleLabels } from "@/lib/copy/status-labels";
import type { UserRole } from "@wecheck/domain";
import { cn } from "@/lib/cn";

export interface UserMenuProps {
  displayName: string;
  role: UserRole;
  onLogout?: () => void;
  className?: string;
}

export function UserMenu({
  displayName,
  role,
  onLogout,
  className,
}: UserMenuProps) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          data-testid="user-menu-trigger"
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
          className="z-dropdown min-w-[12rem] rounded-md border border-border bg-surface-raised p-1 shadow-md"
        >
          <DropdownMenu.Label className="px-3 py-2 text-small text-text-secondary">
            {roleLabels[role]}
          </DropdownMenu.Label>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item
            className="flex min-h-touch cursor-pointer items-center gap-2 rounded-sm px-3 text-body outline-none hover:bg-primary-50"
            onSelect={() => onLogout?.()}
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            {appCopy.logout}
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
