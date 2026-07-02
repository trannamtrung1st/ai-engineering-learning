import { Search, X } from "lucide-react";
import { sessionsListCopy } from "@/lib/copy/sessions-labels";
import type { SessionsSortKey, SessionsStatusFilter } from "@/lib/sessions-list-filters";
import { cn } from "@/lib/cn";

const statusChips: Array<{ value: SessionsStatusFilter; label: string; testId: string }> = [
  { value: "all", label: sessionsListCopy.statusAll, testId: "sessions-status-chip-all" },
  {
    value: "active",
    label: sessionsListCopy.statusActive,
    testId: "sessions-status-chip-active",
  },
  { value: "draft", label: sessionsListCopy.statusDraft, testId: "sessions-status-chip-draft" },
  {
    value: "closed",
    label: sessionsListCopy.statusClosed,
    testId: "sessions-status-chip-closed",
  },
];

const sortOptions: Array<{ value: SessionsSortKey; label: string }> = [
  { value: "date", label: sessionsListCopy.sortDate },
  { value: "class", label: sessionsListCopy.sortClass },
  { value: "subject", label: sessionsListCopy.sortSubject },
];

export interface SessionsListToolbarProps {
  searchInput: string;
  onSearchInputChange: (value: string) => void;
  onClearSearch: () => void;
  statusFilter: SessionsStatusFilter;
  onStatusFilterChange: (value: SessionsStatusFilter) => void;
  sortKey: SessionsSortKey;
  onSortKeyChange: (value: SessionsSortKey) => void;
}

/** AC-06 / TC-AC-06-021 — Notion database toolbar for /sessions listing */
export function SessionsListToolbar({
  searchInput,
  onSearchInputChange,
  onClearSearch,
  statusFilter,
  onStatusFilterChange,
  sortKey,
  onSortKeyChange,
}: SessionsListToolbarProps) {
  return (
    <div
      className="mb-4 rounded-md border border-border bg-surface-raised p-4 shadow-sm"
      data-testid="sessions-list-toolbar"
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="relative min-w-0 flex-1">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
              aria-hidden
            />
            <input
              type="search"
              value={searchInput}
              onChange={(event) => onSearchInputChange(event.target.value)}
              placeholder={sessionsListCopy.searchPlaceholder}
              className="min-h-touch w-full rounded-full border border-border bg-surface-default py-2 pl-10 pr-10 text-body text-text-primary placeholder:text-text-disabled focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
              data-testid="sessions-list-search"
              aria-label={sessionsListCopy.searchPlaceholder}
            />
            {searchInput ? (
              <button
                type="button"
                onClick={onClearSearch}
                className="absolute right-2 top-1/2 flex min-h-touch min-w-touch -translate-y-1/2 items-center justify-center rounded-full text-text-secondary hover:bg-surface-muted hover:text-text-primary"
                aria-label={sessionsListCopy.clearSearch}
                data-testid="sessions-search-clear"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            ) : null}
          </div>

          <label className="flex shrink-0 items-center gap-2 text-small text-text-secondary">
            {sessionsListCopy.sortLabel}
            <select
              value={sortKey}
              onChange={(event) => onSortKeyChange(event.target.value as SessionsSortKey)}
              className="min-h-touch rounded-md border border-border bg-surface-default px-3 text-body text-text-primary"
              data-testid="sessions-list-sort"
            >
              {sortOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div
          className="flex flex-wrap gap-2"
          role="group"
          aria-label="Lọc trạng thái buổi học"
          data-testid="sessions-status-chips"
        >
          {statusChips.map((chip) => {
            const selected = statusFilter === chip.value;
            return (
              <button
                key={chip.value}
                type="button"
                onClick={() => onStatusFilterChange(chip.value)}
                className={cn(
                  "inline-flex min-h-touch items-center rounded-full border px-4 text-small font-medium transition-colors",
                  selected
                    ? "border-primary-200 bg-primary-50 text-primary-600"
                    : "border-border bg-surface-default text-text-secondary hover:border-primary-200 hover:text-text-primary",
                )}
                aria-pressed={selected}
                data-testid={chip.testId}
              >
                {chip.label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
