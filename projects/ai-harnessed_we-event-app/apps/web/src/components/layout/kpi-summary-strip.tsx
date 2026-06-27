import { type ReactNode } from "react";
import Link from "next/link";

import { LiveRefreshIndicator } from "@/components/layout/live-refresh-indicator";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

export interface KpiItem {
  label: string;
  value: ReactNode;
  hint?: string;
  /** Drill-down route for operational detail views (FR-22). */
  href?: string;
}

export interface KpiSummaryStripProps {
  items: KpiItem[];
  className?: string;
  isRefreshing?: boolean;
  /** Inline recovery when a background poll fails but stale KPI data is still shown (TC-NFR-06-012). */
  refreshError?: string;
  onRetryRefresh?: () => void;
}

export function KpiSummaryStrip({
  items,
  className,
  isRefreshing,
  refreshError,
  onRetryRefresh,
}: KpiSummaryStripProps) {
  const showRetry = refreshError && onRetryRefresh;

  return (
    <section
      aria-busy={isRefreshing || undefined}
      aria-label="Key metrics"
      className={cn("space-y-2", className)}
    >
      {refreshError ? (
        <Alert variant="error" title="Could not refresh metrics">
          {refreshError}
          {showRetry ? (
            <div className="mt-3">
              <Button size="sm" variant="secondary" onClick={onRetryRefresh}>
                Retry
              </Button>
            </div>
          ) : null}
        </Alert>
      ) : null}
      {isRefreshing ? <LiveRefreshIndicator /> : null}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {items.map((item) => {
          const card = (
            <>
              <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                {item.label}
              </p>
              <p className="mt-1 text-[length:var(--font-size-xl)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]">
                {item.value}
              </p>
              {item.hint ? (
                <p className="mt-1 text-[length:var(--font-size-xs)] text-[var(--color-text-secondary)]">
                  {item.hint}
                </p>
              ) : null}
            </>
          );

          return (
            <article
              key={item.label}
              className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4"
            >
              {item.href ? (
                <Link
                  href={item.href}
                  className="block rounded-[var(--radius-md)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)]"
                >
                  {card}
                </Link>
              ) : (
                card
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
