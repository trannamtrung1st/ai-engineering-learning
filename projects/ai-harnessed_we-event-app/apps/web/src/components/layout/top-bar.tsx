"use client";

import { CalendarDays, LogOut, User } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { type AppRole, roleLabel } from "@/lib/app-context";
import { cn } from "@/lib/cn";

export interface TopBarProps {
  role: AppRole;
  organizationName?: string;
  userDisplayName?: string;
  className?: string;
}

export function TopBar({
  role,
  organizationName,
  userDisplayName = "Signed in user",
  className,
}: TopBarProps) {
  return (
    <header
      className={cn(
        "sticky top-0 z-40 border-b border-[var(--color-border-default)] bg-[var(--color-bg-surface)]",
        className,
      )}
    >
      <div className="mx-auto flex h-14 max-w-[var(--container-max-app)] items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex items-center gap-2 rounded-[var(--radius-md)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)]"
          >
            <CalendarDays className="h-5 w-5 text-[var(--color-action-primary-bg)]" aria-hidden />
            <span>We Event</span>
          </Link>
          <span className="hidden text-[var(--color-border-strong)] sm:inline" aria-hidden>
            /
          </span>
          <span className="hidden text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)] sm:inline">
            {roleLabel(role)}
            {organizationName ? ` · ${organizationName}` : null}
          </span>
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="secondary" size="sm" aria-label="Account menu">
              <User className="h-4 w-4" aria-hidden />
              <span className="max-w-[10rem] truncate">{userDisplayName}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>{userDisplayName}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem>
              <User className="h-4 w-4" aria-hidden />
              Account
            </DropdownMenuItem>
            <DropdownMenuItem className="text-[var(--color-status-rejected)] focus:text-[var(--color-status-rejected)]">
              <LogOut className="h-4 w-4" aria-hidden />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
