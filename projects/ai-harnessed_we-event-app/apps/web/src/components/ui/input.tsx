import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", error, ...props }, ref) => (
    <input
      type={type}
      className={cn(
        "flex h-10 w-full rounded-[var(--radius-md)] border bg-[var(--color-bg-surface)] px-3 py-2 text-[length:var(--font-size-sm)] text-[var(--color-text-primary)] transition-colors placeholder:text-[var(--color-text-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
        error
          ? "border-[var(--color-status-rejected)]"
          : "border-[var(--color-border-default)]",
        className,
      )}
      ref={ref}
      aria-invalid={error || undefined}
      {...props}
    />
  ),
);
Input.displayName = "Input";
