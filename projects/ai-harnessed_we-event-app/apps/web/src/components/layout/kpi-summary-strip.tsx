import { type ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface KpiItem {
  label: string;
  value: ReactNode;
  hint?: string;
}

export interface KpiSummaryStripProps {
  items: KpiItem[];
  className?: string;
}

export function KpiSummaryStrip({ items, className }: KpiSummaryStripProps) {
  return (
    <section
      aria-label="Key metrics"
      className={cn(
        "grid gap-4 sm:grid-cols-2 xl:grid-cols-4",
        className,
      )}
    >
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
    </section>
  );
}
