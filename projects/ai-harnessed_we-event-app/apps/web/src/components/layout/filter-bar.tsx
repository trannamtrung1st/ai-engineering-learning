"use client";

import { Filter } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

export interface FilterBarProps {
  children: ReactNode;
  className?: string;
}

export function FilterBar({ children, className }: FilterBarProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <section
      aria-label="Filters"
      className={cn(
        "rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4",
        className,
      )}
    >
      <div className="mb-3 flex items-center justify-between lg:hidden">
        <p className="text-[length:var(--font-size-sm)] font-[var(--font-weight-semibold)]">
          Filters
        </p>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setCollapsed((value) => !value)}
          aria-expanded={!collapsed}
        >
          <Filter className="h-4 w-4" aria-hidden />
          {collapsed ? "Show" : "Hide"}
        </Button>
      </div>
      <div className={cn("flex flex-wrap items-end gap-3", collapsed && "hidden lg:flex")}>
        {children}
      </div>
    </section>
  );
}
