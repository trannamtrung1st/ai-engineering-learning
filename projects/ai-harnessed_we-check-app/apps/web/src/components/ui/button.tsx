import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

const variantClasses = {
  primary:
    "bg-primary-600 text-primary-foreground shadow-sm hover:bg-primary-700 hover:shadow-md disabled:opacity-50",
  secondary:
    "bg-surface-raised text-text-primary border border-border shadow-sm hover:bg-surface-muted disabled:opacity-50",
  outline:
    "border border-primary-600 bg-transparent text-primary-600 hover:bg-primary-50 disabled:opacity-50",
  ghost:
    "bg-transparent text-text-primary hover:bg-primary-50 disabled:opacity-50",
  danger:
    "bg-danger-500 text-primary-foreground shadow-sm hover:opacity-90 disabled:opacity-50",
} as const;

const sizeClasses = {
  sm: "h-9 px-3 text-small rounded-md",
  md: "min-h-touch px-4 text-body rounded-md",
  lg: "min-h-touch px-6 text-body rounded-md",
} as const;

export type ButtonVariant = keyof typeof variantClasses;
export type ButtonSize = keyof typeof sizeClasses;

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      className,
      variant = "primary",
      size = "md",
      loading = false,
      disabled,
      children,
      ...props
    },
    ref,
  ) {
    return (
      <button
        ref={ref}
        type="button"
        className={cn(
          "inline-flex items-center justify-center gap-2 font-medium transition-all duration-normal focus-visible:outline-none motion-safe:active:scale-[0.98]",
          variantClasses[variant],
          sizeClasses[size],
          className,
        )}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading ? (
          <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
        ) : null}
        {children}
      </button>
    );
  },
);
