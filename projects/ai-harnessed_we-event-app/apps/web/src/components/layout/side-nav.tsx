"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { type AppRole, type NavItem } from "@/lib/app-context";
import { cn } from "@/lib/cn";

export type { NavItem };

export interface SideNavProps {
  items: NavItem[];
  role: AppRole;
  className?: string;
}

export function SideNav({ items, role, className }: SideNavProps) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const visibleItems = items.filter((item) => item.roles.includes(role));

  if (visibleItems.length === 0) {
    return null;
  }

  const navContent = (
    <nav aria-label="Section navigation" className="flex flex-col gap-1 p-3">
      {visibleItems.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={() => setOpen(false)}
            className={cn(
              "rounded-[var(--radius-md)] px-3 py-2 text-[length:var(--font-size-sm)] font-[var(--font-weight-medium)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)]",
              active
                ? "bg-[var(--color-action-primary-bg)] text-[var(--color-action-primary-text)]"
                : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-subtle)] hover:text-[var(--color-text-primary)]",
            )}
            aria-current={active ? "page" : undefined}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <>
      <div className="border-b border-[var(--color-border-default)] p-3 lg:hidden">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="app-side-nav"
        >
          {open ? <X className="h-4 w-4" aria-hidden /> : <Menu className="h-4 w-4" aria-hidden />}
          Navigation
        </Button>
      </div>

      <aside
        id="app-side-nav"
        className={cn(
          "w-full shrink-0 border-[var(--color-border-default)] bg-[var(--color-bg-surface)] lg:w-60 lg:border-r",
          open ? "block" : "hidden lg:block",
          className,
        )}
      >
        {navContent}
      </aside>
    </>
  );
}
