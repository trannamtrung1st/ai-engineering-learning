import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/cn";
import { Label } from "@/components/ui/label";

export interface FieldProps {
  id: string;
  label: string;
  helperText?: string;
  errorText?: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
}

export function Field({
  id,
  label,
  helperText,
  errorText,
  required,
  children,
  className,
}: FieldProps) {
  const helperId = helperText ? `${id}-helper` : undefined;
  const errorId = errorText ? `${id}-error` : undefined;
  const describedBy = [helperId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={cn("space-y-2", className)}>
      <Label htmlFor={id}>
        {label}
        {required ? (
          <span className="ml-1 text-[var(--color-status-rejected)]" aria-hidden>
            *
          </span>
        ) : null}
      </Label>
      <div aria-describedby={describedBy}>{children}</div>
      <div className="min-h-[1.25rem]">
        {errorText ? (
          <p
            id={errorId}
            className="text-[length:var(--font-size-sm)] text-[var(--color-status-rejected)]"
            role="alert"
          >
            {errorText}
          </p>
        ) : helperText ? (
          <p
            id={helperId}
            className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]"
          >
            {helperText}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export interface NumberInputProps extends InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
}

export const NumberInput = forwardRef<HTMLInputElement, NumberInputProps>(
  ({ className, error, ...props }, ref) => (
    <input
      type="number"
      className={cn(
        "flex h-10 w-full rounded-[var(--radius-md)] border bg-[var(--color-bg-surface)] px-3 py-2 text-[length:var(--font-size-sm)] text-[var(--color-text-primary)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
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
NumberInput.displayName = "NumberInput";

export interface DateTimeInputProps extends InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
  timezoneHint?: string;
}

export const DateTimeInput = forwardRef<HTMLInputElement, DateTimeInputProps>(
  ({ className, error, timezoneHint, type = "datetime-local", ...props }, ref) => (
    <div className="space-y-1">
      <input
        type={type}
        className={cn(
          "flex h-10 w-full rounded-[var(--radius-md)] border bg-[var(--color-bg-surface)] px-3 py-2 text-[length:var(--font-size-sm)] text-[var(--color-text-primary)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
          error
            ? "border-[var(--color-status-rejected)]"
            : "border-[var(--color-border-default)]",
          className,
        )}
        ref={ref}
        aria-invalid={error || undefined}
        {...props}
      />
      {timezoneHint ? (
        <p className="text-[length:var(--font-size-xs)] text-[var(--color-text-secondary)]">
          {timezoneHint}
        </p>
      ) : null}
    </div>
  ),
);
DateTimeInput.displayName = "DateTimeInput";
