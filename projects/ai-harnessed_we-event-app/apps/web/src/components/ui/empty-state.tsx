"use client";

import Link from "next/link";
import { type ReactNode } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/cn";

export interface EmptyStateProps {
  title: string;
  description: string;
  actionLabel?: string;
  actionHref?: string;
  onAction?: () => void;
  icon?: ReactNode;
  className?: string;
}

export function EmptyState({
  title,
  description,
  actionLabel,
  actionHref,
  onAction,
  icon,
  className,
}: EmptyStateProps) {
  const showAction = actionLabel && (actionHref || onAction);

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-[var(--radius-lg)] border border-dashed border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-6 py-12 text-center",
        className,
      )}
    >
      {icon ? (
        <div className="mb-4 text-[var(--color-text-secondary)]" aria-hidden>
          {icon}
        </div>
      ) : null}
      <h3 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]">
        {title}
      </h3>
      <p className="mt-2 max-w-md text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
        {description}
      </p>
      {showAction ? (
        actionHref ? (
          <Link href={actionHref} className={cn(buttonVariants(), "mt-6")}>
            {actionLabel}
          </Link>
        ) : (
          <Button className="mt-6" onClick={onAction}>
            {actionLabel}
          </Button>
        )
      ) : null}
    </div>
  );
}
