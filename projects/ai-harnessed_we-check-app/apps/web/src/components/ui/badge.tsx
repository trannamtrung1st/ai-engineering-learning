import { forwardRef } from "react";
import { cn } from "@/lib/cn";

const variantClasses = {
  default: "bg-primary-100 text-primary-700 border-transparent",
  outline: "bg-transparent text-text-primary border-border",
} as const;

export type BadgeVariant = keyof typeof variantClasses;

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { className, variant = "default", ...props },
  ref,
) {
  return (
    <span
      ref={ref}
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-small font-medium",
        variantClasses[variant],
        className,
      )}
      {...props}
    />
  );
});
