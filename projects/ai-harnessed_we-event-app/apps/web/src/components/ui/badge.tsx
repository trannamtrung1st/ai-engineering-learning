import { cva, type VariantProps } from "class-variance-authority";
import { type HTMLAttributes } from "react";

import { cn } from "@/lib/cn";
import {
  statusTokenMap,
  type DomainStatus,
} from "@/lib/status-tokens";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-[var(--radius-pill)] px-2.5 py-0.5 text-[length:var(--font-size-xs)] font-[var(--font-weight-medium)]",
  {
    variants: {
      variant: {
        default:
          "bg-[var(--color-bg-subtle)] text-[var(--color-text-primary)]",
        outline:
          "border border-[var(--color-border-default)] bg-transparent text-[var(--color-text-primary)]",
        semantic:
          "bg-[var(--status-bg)] text-[var(--status-fg)]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  status?: DomainStatus;
}

export function Badge({
  className,
  variant,
  status,
  children,
  ...props
}: BadgeProps) {
  if (status) {
    const tokens = statusTokenMap[status];
    return (
      <span
        className={cn(badgeVariants({ variant: "semantic" }), className)}
        data-domain-status={status}
        {...props}
      >
        <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full bg-current opacity-80" />
        <span>{children ?? tokens.label}</span>
      </span>
    );
  }

  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props}>
      {children}
    </span>
  );
}
