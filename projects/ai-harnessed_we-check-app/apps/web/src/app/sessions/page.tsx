import { SessionStatus } from "@wecheck/domain";
import { BarChart3, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { SessionsListToolbar } from "@/components/instructor/sessions-list-toolbar";
import { RoleHomeHub } from "@/components/layout/role-home-hub";
import { PageHeader } from "@/components/layout/page-header";
import { SessionCard } from "@/components/domain/session/session-card";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert } from "@/components/ui/alert";
import { useSessionsList } from "@/hooks/use-sessions-list";
import { sessionsListCopy } from "@/lib/copy/sessions-labels";
import { sessionStatusLabels } from "@/lib/copy/status-labels";
import type { SessionListItem } from "@/lib/sessions-api";
import {
  buildSessionsListDisplayEntries,
  paginateSessionsListEntries,
  SESSIONS_LIST_PAGE_SIZE,
  type SessionsSortKey,
  type SessionsStatusFilter,
} from "@/lib/sessions-list-filters";

const instructorHubIcons = {
  "/sessions/new": Plus,
  "/reports": BarChart3,
} as const;

const SEARCH_DEBOUNCE_MS = 300;

function ListSkeleton() {
  return (
    <div className="flex flex-col gap-3" data-testid="sessions-list-loading" aria-busy="true">
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

function SessionsListResults({
  items,
  search,
  statusFilter,
  sortKey,
}: {
  items: SessionListItem[];
  search: string;
  statusFilter: SessionsStatusFilter;
  sortKey: SessionsSortKey;
}) {
  const [visibleCount, setVisibleCount] = useState(SESSIONS_LIST_PAGE_SIZE);

  useEffect(() => {
    setVisibleCount(SESSIONS_LIST_PAGE_SIZE);
  }, [search, statusFilter, sortKey]);

  const displayEntries = useMemo(
    () =>
      buildSessionsListDisplayEntries(items, {
        search,
        statusFilter,
        sortKey,
        sectionLabels: {
          active: sessionStatusLabels[SessionStatus.Active],
          draft: sessionStatusLabels[SessionStatus.Draft],
          closed: sessionStatusLabels[SessionStatus.Closed],
        },
      }),
    [items, search, statusFilter, sortKey],
  );

  const { visibleEntries, hasMore } = paginateSessionsListEntries(
    displayEntries,
    visibleCount,
  );

  if (displayEntries.length === 0) {
    return (
      <EmptyState
        icon={Plus}
        title="Không có buổi học"
        description={sessionsListCopy.filteredEmpty}
      />
    );
  }

  return (
    <>
      <div data-testid="sessions-list-results">
        {visibleEntries.map((entry, index) => {
          if (entry.kind === "section") {
            return (
              <h2 key={`${entry.label}-${index}`} className="mb-3 text-h2 font-semibold">
                {entry.label}
              </h2>
            );
          }

          return (
            <div key={entry.session.id} className="mb-3">
              <SessionCard session={entry.session} />
            </div>
          );
        })}
      </div>

      {hasMore ? (
        <div className="mt-4 flex justify-center">
          <Button
            type="button"
            variant="outline"
            data-testid="sessions-list-load-more"
            onClick={() => setVisibleCount((count) => count + SESSIONS_LIST_PAGE_SIZE)}
          >
            {sessionsListCopy.loadMore}
          </Button>
        </div>
      ) : null}
    </>
  );
}

/** FR-04 / AC-04 / AC-06 — instructor session list with listing toolbar */
export function SessionsListPage() {
  const query = useSessionsList();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<SessionsStatusFilter>("all");
  const [sortKey, setSortKey] = useState<SessionsSortKey>("date");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim());
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const pageHeader = (
  <PageHeader
      title="Buổi học"
      description="Quản lý buổi học và điểm danh"
      actions={
        <Link
          to="/sessions/new"
          className="inline-flex min-h-touch items-center justify-center rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700"
          data-testid="create-session-link"
        >
          Tạo buổi học
        </Link>
      }
    />
  );

  if (query.isLoading) {
    return (
      <div data-testid="sessions-list-page">
        <RoleHomeHub variant="instructor" icons={instructorHubIcons} />
        {pageHeader}
        <SessionsListToolbar
          searchInput={searchInput}
          onSearchInputChange={setSearchInput}
          onClearSearch={() => {
            setSearchInput("");
            setSearch("");
          }}
          statusFilter={statusFilter}
          onStatusFilterChange={setStatusFilter}
          sortKey={sortKey}
          onSortKeyChange={setSortKey}
        />
        <ListSkeleton />
      </div>
    );
  }

  if (query.isError) {
    return (
      <div data-testid="sessions-list-page">
        <RoleHomeHub variant="instructor" icons={instructorHubIcons} />
        <PageHeader title="Buổi học" description="Quản lý buổi học và điểm danh" />
        <Alert variant="danger" title="Không thể tải danh sách">
          Vui lòng thử lại sau.
        </Alert>
      </div>
    );
  }

  const items = query.data?.items ?? [];

  if (items.length === 0) {
    return (
      <div data-testid="sessions-list-page">
        <RoleHomeHub variant="instructor" icons={instructorHubIcons} />
        <PageHeader title="Buổi học" description="Quản lý buổi học và điểm danh" />
        <EmptyState
          icon={Plus}
          title="Chưa có buổi học"
          description="Tạo buổi học mới để bắt đầu điểm danh."
          action={
            <Link
              to="/sessions/new"
              className="inline-flex min-h-touch items-center justify-center rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700"
            >
              Tạo buổi học
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div data-testid="sessions-list-page">
      <RoleHomeHub variant="instructor" icons={instructorHubIcons} />
      {pageHeader}
      <SessionsListToolbar
        searchInput={searchInput}
        onSearchInputChange={setSearchInput}
        onClearSearch={() => {
          setSearchInput("");
          setSearch("");
        }}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        sortKey={sortKey}
        onSortKeyChange={setSortKey}
      />
      <SessionsListResults
        items={items}
        search={search}
        statusFilter={statusFilter}
        sortKey={sortKey}
      />
    </div>
  );
}
