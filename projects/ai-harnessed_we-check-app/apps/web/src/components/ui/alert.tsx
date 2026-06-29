import { cn } from "@/lib/cn";
import type { LucideIcon } from "lucide-react";

const variantClasses = {
  info: "border-info-500 bg-info-50 text-info-500",
  success: "border-success-500 bg-success-50 text-success-500",
  warning: "border-warning-500 bg-warning-50 text-warning-500",
  danger: "border-danger-500 bg-danger-50 text-danger-500",
} as const;

export type AlertVariant = keyof typeof variantClasses;

export interface AlertProps {
  variant?: AlertVariant;
  title?: string;
  children: React.ReactNode;
  icon?: LucideIcon;
  className?: string;
}

export function Alert({
  variant = "info",
  title,
  children,
  icon: Icon,
  className,
}: AlertProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex gap-3 rounded-md border px-4 py-3 text-body",
        variantClasses[variant],
        className,
      )}
    >
      {Icon ? <Icon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" /> : null}
      <div>
        {title ? <p className="font-semibold">{title}</p> : null}
        <div className={title ? "mt-1" : undefined}>{children}</div>
      </div>
    </div>
  );
}
