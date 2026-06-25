import { cva, type VariantProps } from "class-variance-authority";
import { AlertCircle, CheckCircle2, Info, TriangleAlert } from "lucide-react";
import { type HTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/cn";

const alertVariants = cva(
  "relative w-full rounded-[var(--radius-md)] border p-4 text-[length:var(--font-size-sm)]",
  {
    variants: {
      variant: {
        info: "border-[var(--color-status-eligible)]/30 bg-[var(--color-bg-subtle)] text-[var(--color-text-primary)]",
        success:
          "border-[var(--color-status-registered)]/30 bg-[var(--color-bg-subtle)] text-[var(--color-text-primary)]",
        warning:
          "border-[var(--color-status-waitlisted)]/30 bg-[var(--color-bg-subtle)] text-[var(--color-text-primary)]",
        error:
          "border-[var(--color-status-rejected)]/30 bg-[var(--color-bg-subtle)] text-[var(--color-text-primary)]",
      },
    },
    defaultVariants: {
      variant: "info",
    },
  },
);

const iconMap = {
  info: Info,
  success: CheckCircle2,
  warning: TriangleAlert,
  error: AlertCircle,
} as const;

export interface AlertProps
  extends HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {
  title?: string;
  action?: ReactNode;
}

export function Alert({
  className,
  variant = "info",
  title,
  action,
  children,
  ...props
}: AlertProps) {
  const Icon = iconMap[variant ?? "info"];
  const role = variant === "error" || variant === "warning" ? "alert" : "status";

  return (
    <div
      role={role}
      className={cn(alertVariants({ variant }), className)}
      {...props}
    >
      <div className="flex gap-3">
        <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <div className="flex-1 space-y-1">
          {title ? (
            <p className="font-[var(--font-weight-semibold)]">{title}</p>
          ) : null}
          {children ? <div className="text-[var(--color-text-secondary)]">{children}</div> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
    </div>
  );
}
