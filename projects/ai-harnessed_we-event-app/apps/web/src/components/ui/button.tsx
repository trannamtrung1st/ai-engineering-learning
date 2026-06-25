import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-[var(--radius-md)] font-[var(--font-weight-medium)] transition-colors duration-[var(--motion-duration-fast)] ease-[var(--motion-easing-standard)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:bg-[var(--color-action-disabled-bg)] disabled:text-[var(--color-action-disabled-text)]",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--color-action-primary-bg)] text-[var(--color-action-primary-text)] hover:bg-[var(--color-action-primary-hover)]",
        secondary:
          "bg-[var(--color-action-secondary-bg)] text-[var(--color-text-primary)] hover:bg-[var(--color-border-strong)]",
        danger:
          "bg-[var(--color-status-rejected)] text-[var(--color-status-rejected-fg)] hover:opacity-90",
        ghost:
          "bg-transparent text-[var(--color-text-primary)] hover:bg-[var(--color-bg-subtle)]",
        link: "bg-transparent text-[var(--color-action-primary-bg)] underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-8 px-3 text-[length:var(--font-size-sm)]",
        md: "h-10 px-4 text-[length:var(--font-size-sm)]",
        lg: "h-11 px-6 text-[length:var(--font-size-md)]",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant,
      size,
      asChild = false,
      loading = false,
      disabled,
      children,
      ...props
    },
    ref,
  ) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
        {children}
      </Comp>
    );
  },
);
Button.displayName = "Button";

export { buttonVariants };
