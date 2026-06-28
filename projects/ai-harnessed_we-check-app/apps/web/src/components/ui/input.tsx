import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, error, hint, id, ...props },
  ref,
) {
  const hintId = hint && id ? `${id}-hint` : undefined;
  const errorId = error && id ? `${id}-error` : undefined;

  return (
    <div className="flex flex-col gap-1">
      <input
        ref={ref}
        id={id}
        className={cn(
          "min-h-touch w-full rounded-md border border-border bg-surface-raised px-3 py-2 text-body text-text-primary placeholder:text-text-disabled",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500",
          error && "border-danger-500",
          className,
        )}
        aria-invalid={error ? true : undefined}
        aria-describedby={[hintId, errorId].filter(Boolean).join(" ") || undefined}
        {...props}
      />
      {hint ? (
        <p id={hintId} className="text-small text-text-secondary">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-small text-danger-500" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
});
