import { type ReactNode } from "react";

import { LiveRefreshIndicator } from "@/components/layout/live-refresh-indicator";
import { cn } from "@/lib/cn";

export interface KpiItem {
  label: string;
  value: ReactNode;
  hint?: string;
}

export interface KpiSummaryStripProps {
  items: KpiItem[];
  className?: string;
  isRefreshing?: boolean;
}

export function KpiSummaryStrip({ items, className, isRefreshing }: KpiSummaryStripProps) {
  return (
    <section
      aria-busy={isRefreshing || undefined}
      aria-label="Key metrics"
      className={cn("space-y-2", className)}
    >
      {isRefreshing ? <LiveRefreshIndicator /> : null}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {items.map((item) => (
          <article
            key={item.label}
            className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4"
          >
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
          </article>
        ))}
      </div>
    </section>
  );
}
