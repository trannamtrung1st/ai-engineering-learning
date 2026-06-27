"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

export interface PaginationProps {
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  className?: string;
  total?: number;
  pageSize?: number;
}

function itemRangeLabel(page: number, pageSize: number, total: number): string {
  if (total === 0) {
    return "Showing 0 of 0";
  }
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);
  return `Showing ${start}–${end} of ${total}`;
}

export function Pagination({
  page,
  pageCount,
  onPageChange,
  className,
  total,
  pageSize,
}: PaginationProps) {
  const canPrev = page > 1;
  const canNext = page < pageCount;
  const rangeLabel =
    total !== undefined && pageSize !== undefined
      ? itemRangeLabel(page, pageSize, total)
      : null;

  return (
    <nav
      className={cn("flex items-center justify-between gap-4", className)}
      aria-label="Pagination"
    >
      <div className="space-y-0.5">
        {rangeLabel ? (
          <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
            {rangeLabel}
          </p>
        ) : null}
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          Page {page} of {Math.max(pageCount, 1)}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onPageChange(page - 1)}
          disabled={!canPrev}
          aria-label="Previous page"
        >
          <ChevronLeft className="h-4 w-4" aria-hidden />
          Previous
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onPageChange(page + 1)}
          disabled={!canNext}
          aria-label="Next page"
        >
          Next
          <ChevronRight className="h-4 w-4" aria-hidden />
        </Button>
      </div>
    </nav>
  );
}
