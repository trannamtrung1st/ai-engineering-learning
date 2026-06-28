import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  "aria-label": string;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  function IconButton({ className, children, ...props }, ref) {
    return (
      <button
        ref={ref}
        type="button"
        className={cn(
          "inline-flex min-h-touch min-w-touch items-center justify-center rounded-md text-text-primary transition-colors hover:bg-primary-50 focus-visible:outline-none",
          className,
        )}
        {...props}
      >
        {children}
      </button>
    );
  },
);
