"use client";

import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Pagination } from "@/components/ui/pagination";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/cn";

export interface DataTableProps<TData> {
  columns: ColumnDef<TData, unknown>[];
  data: TData[];
  filterPlaceholder?: string;
  filterColumnId?: string;
  pageSize?: number;
  emptyTitle?: string;
  emptyDescription?: string;
  className?: string;
}

export function DataTable<TData>({
  columns,
  data,
  filterPlaceholder = "Filter rows…",
  filterColumnId,
  pageSize = 10,
  emptyTitle = "No rows to display",
  emptyDescription = "Adjust filters or check back when data is available.",
  className,
}: DataTableProps<TData>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");

  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: { pageSize },
    },
    globalFilterFn: filterColumnId
      ? (row, _columnId, filterValue) => {
          const value = row.getValue(filterColumnId);
          return String(value ?? "")
            .toLowerCase()
            .includes(String(filterValue).toLowerCase());
        }
      : undefined,
  });

  const pageCount = table.getPageCount();
  const pageIndex = table.getState().pagination.pageIndex;
  const rows = table.getRowModel().rows;

  const filterControl = useMemo(
    () => (
      <Input
        value={globalFilter}
        onChange={(event) => setGlobalFilter(event.target.value)}
        placeholder={filterPlaceholder}
        aria-label={filterPlaceholder}
        className="max-w-sm"
      />
    ),
    [filterPlaceholder, globalFilter],
  );

  if (data.length === 0) {
    return (
      <div className={cn("space-y-4", className)}>
        {filterControl}
        <EmptyState title={emptyTitle} description={emptyDescription} />
      </div>
    );
  }

  return (
    <div className={cn("space-y-4", className)}>
      {filterControl}
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id}>
                  {header.isPlaceholder ? null : header.column.getCanSort() ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 font-[var(--font-weight-semibold)] hover:text-[var(--color-text-primary)]"
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      <span aria-hidden className="text-[var(--color-text-secondary)]">
                        {{
                          asc: "↑",
                          desc: "↓",
                        }[header.column.getIsSorted() as string] ?? "↕"}
                      </span>
                    </button>
                  ) : (
                    flexRender(header.column.columnDef.header, header.getContext())
                  )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={columns.length} className="h-24 text-center">
                <span className="text-[var(--color-text-secondary)]">
                  No rows match the current filter.
                </span>
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      <Pagination
        page={pageIndex + 1}
        pageCount={pageCount}
        onPageChange={(page) => table.setPageIndex(page - 1)}
      />
    </div>
  );
}
