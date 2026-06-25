"use client";

import { X } from "lucide-react";
import { type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

export interface DetailsDrawerProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}

export function DetailsDrawer({
  open,
  title,
  onClose,
  children,
  className,
}: DetailsDrawerProps) {
  if (!open) return null;

  return (
    <>
      <button
        type="button"
        className="fixed inset-0 z-40 bg-[var(--color-text-primary)]/30 lg:hidden"
        aria-label="Close details panel"
        onClick={onClose}
      />
      <aside
        className={cn(
          "fixed inset-y-0 right-0 z-50 w-full max-w-md border-l border-[var(--color-border-default)] bg-[var(--color-bg-surface)] shadow-[var(--shadow-lg)] lg:static lg:max-w-none lg:shadow-none",
          className,
        )}
        aria-label={title}
      >
        <div className="flex items-center justify-between border-b border-[var(--color-border-default)] px-4 py-3">
          <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
            {title}
          </h2>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close details">
            <X className="h-4 w-4" aria-hidden />
          </Button>
        </div>
        <div className="overflow-y-auto p-4">{children}</div>
      </aside>
    </>
  );
}
