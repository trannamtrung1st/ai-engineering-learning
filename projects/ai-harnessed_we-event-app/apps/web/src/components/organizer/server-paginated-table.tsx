"use client";

import { type ReactNode } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/cn";

export interface ServerPaginatedTableProps<T> {
  columns: Array<{
    id: string;
    header: ReactNode;
    cell: (row: T) => ReactNode;
    className?: string;
  }>;
  items: T[];
  rowKey: (row: T) => string;
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  isLoading?: boolean;
  isError?: boolean;
  errorMessage?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  toolbar?: ReactNode;
  className?: string;
}

export function ServerPaginatedTable<T>({
  columns,
  items,
  rowKey,
  page,
  pageSize,
  total,
  totalPages,
  onPageChange,
  isLoading,
  isError,
  errorMessage,
  emptyTitle = "No rows to display",
  emptyDescription = "Adjust filters or check back when data is available.",
  toolbar,
  className,
}: ServerPaginatedTableProps<T>) {
  if (isLoading) {
    return (
      <div className={cn("space-y-4", className)}>
        {toolbar}
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className={cn("space-y-4", className)}>
        {toolbar}
        <EmptyState
          title="Could not load data"
          description={errorMessage ?? "Try again in a moment."}
        />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className={cn("space-y-4", className)}>
        {toolbar}
        <EmptyState title={emptyTitle} description={emptyDescription} />
        {total > 0 ? (
          <Pagination
            page={page}
            pageCount={Math.max(totalPages, 1)}
            total={total}
            pageSize={pageSize}
            onPageChange={onPageChange}
          />
        ) : null}
      </div>
    );
  }

  return (
    <div className={cn("space-y-4", className)}>
      {toolbar}
      <div className="overflow-x-auto rounded-[var(--radius-lg)] border border-[var(--color-border-default)]">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-[var(--color-bg-surface)]">
            <TableRow>
              {columns.map((column) => (
                <TableHead key={column.id} className={column.className}>
                  {column.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((row) => (
              <TableRow key={rowKey(row)}>
                {columns.map((column) => (
                  <TableCell key={column.id} className={column.className}>
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <Pagination
        page={page}
        pageCount={Math.max(totalPages, 1)}
        total={total}
        pageSize={pageSize}
        onPageChange={onPageChange}
      />
    </div>
  );
}
