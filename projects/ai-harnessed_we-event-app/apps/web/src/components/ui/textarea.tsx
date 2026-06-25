import { forwardRef, type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, error, ...props }, ref) => (
    <textarea
      className={cn(
        "flex min-h-[5rem] w-full rounded-[var(--radius-md)] border bg-[var(--color-bg-surface)] px-3 py-2 text-[length:var(--font-size-sm)] text-[var(--color-text-primary)] transition-colors placeholder:text-[var(--color-text-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
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
Textarea.displayName = "Textarea";
