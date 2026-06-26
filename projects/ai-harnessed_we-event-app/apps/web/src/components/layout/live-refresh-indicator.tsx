import { cn } from "@/lib/cn";

export interface LiveRefreshIndicatorProps {
  className?: string;
}

/** Subtle NFR-06 background-poll affordance — preserves layout while data refetches. */
export function LiveRefreshIndicator({ className }: LiveRefreshIndicatorProps) {
  return (
    <span
      className={cn(
        "text-[length:var(--font-size-xs)] text-[var(--color-text-secondary)]",
        className,
      )}
      aria-live="polite"
    >
      Refreshing…
    </span>
  );
}
