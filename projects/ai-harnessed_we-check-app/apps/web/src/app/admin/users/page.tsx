import { UserRole } from "@wecheck/domain";
import { Plus, Search, Upload, Users, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  UserListTable,
  UserListTableError,
} from "@/components/admin/user-list-table";
import { useAuthUser } from "@/components/auth/require-auth";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUsersList } from "@/hooks/use-users-list";
import { userCopy } from "@/lib/copy/user-labels";
import { roleLabels } from "@/lib/copy/status-labels";
import {
  normalizeUsersSearchQuery,
  paginateUsers,
  parseUsersSortColumn,
  parseUsersSortDirection,
  sortUsers,
  USERS_PAGE_SIZE,
  usersPageCount,
  type UsersSortColumn,
  type UsersSortDirection,
} from "@/lib/users-list-filters";

const SEARCH_DEBOUNCE_MS = 300;

function FilterChip({
  label,
  onRemove,
  testId,
}: {
  label: string;
  onRemove: () => void;
  testId: string;
}) {
  return (
    <button
      type="button"
      className="inline-flex min-h-touch items-center gap-1 rounded-full border border-border bg-surface px-3 text-small text-text-primary hover:bg-surface-muted"
      onClick={onRemove}
      data-testid={testId}
      aria-label={`${userCopy.removeFilter}: ${label}`}
    >
      <span>{label}</span>
      <X className="h-3.5 w-3.5" aria-hidden />
    </button>
  );
}

function UserListPagination({
  currentPage,
  totalPages,
  onPageChange,
  loading,
}: {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  loading?: boolean;
}) {
  if (totalPages <= 1) return null;

  return (
    <nav
      className="mt-4 flex items-center justify-center gap-2"
      aria-label="Phân trang danh sách người dùng"
      data-testid="user-list-pagination"
    >
      {Array.from({ length: totalPages }, (_, index) => {
        const page = index + 1;
        const active = page === currentPage;
        return (
          <Button
            key={page}
            type="button"
            size="sm"
            variant={active ? "primary" : "outline"}
            loading={loading && page > currentPage}
            data-testid={`user-list-page-${page}`}
            aria-current={active ? "page" : undefined}
            onClick={() => onPageChange(page)}
          >
            {page}
          </Button>
        );
      })}
    </nav>
  );
}

/** FR-01 / AC-01 / NFR-11 — admin user list with search and filters */
export function AdminUsersPage() {
  const authUser = useAuthUser();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialQuery = searchParams.get("q") ?? "";
  const [searchInput, setSearchInput] = useState(initialQuery);
  const [search, setSearch] = useState(() => normalizeUsersSearchQuery(initialQuery) ?? "");
  const [roleFilter, setRoleFilter] = useState<string>("");
  const [activeFilter, setActiveFilter] = useState<string>("");
  const [sortColumn, setSortColumn] = useState<UsersSortColumn>(() =>
    parseUsersSortColumn(searchParams.get("sort")),
  );
  const [sortDirection, setSortDirection] = useState<UsersSortDirection>(() =>
    parseUsersSortDirection(searchParams.get("dir")),
  );
  const [currentPage, setCurrentPage] = useState(1);

  useEffect(() => {
    const timer = setTimeout(() => {
      const normalized = normalizeUsersSearchQuery(searchInput) ?? "";
      setSearch(normalized);
      setCurrentPage(1);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (normalized) next.set("q", normalized);
          else next.delete("q");
          return next;
        },
        { replace: true },
      );
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput, setSearchParams]);

  const handleSortChange = useCallback(
    (column: UsersSortColumn, direction: UsersSortDirection) => {
      setSortColumn(column);
      setSortDirection(direction);
      setCurrentPage(1);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("sort", column);
          next.set("dir", direction);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const filters = useMemo(
    () => ({
      search: search || undefined,
      role:
        roleFilter === UserRole.Student ||
        roleFilter === UserRole.Instructor ||
        roleFilter === UserRole.TrainingOfficeAdmin
          ? roleFilter
          : undefined,
      active:
        activeFilter === "true" ? true : activeFilter === "false" ? false : undefined,
    }),
    [search, roleFilter, activeFilter],
  );

  const query = useUsersList(filters);

  const users = useMemo(
    () => query.data?.pages.flatMap((page) => page.items) ?? [],
    [query.data?.pages],
  );
  const sortedUsers = useMemo(
    () => sortUsers(users, sortColumn, sortDirection),
    [users, sortColumn, sortDirection],
  );

  const loadedPages = usersPageCount(sortedUsers.length, USERS_PAGE_SIZE);
  const totalPages = query.hasNextPage ? loadedPages + 1 : loadedPages;
  const pageUsers = paginateUsers(sortedUsers, currentPage, USERS_PAGE_SIZE);

  useEffect(() => {
    const needed = currentPage * USERS_PAGE_SIZE;
    if (needed > sortedUsers.length && query.hasNextPage && !query.isFetchingNextPage) {
      void query.fetchNextPage();
    }
  }, [currentPage, sortedUsers.length, query.hasNextPage, query.isFetchingNextPage, query.fetchNextPage]);

  const hasFilters = Boolean(search || roleFilter || activeFilter);

  if (authUser.role !== UserRole.TrainingOfficeAdmin) {
    return <ForbiddenPage homeTo="/check-in" />;
  }

  const filterChips: Array<{ id: string; label: string; onRemove: () => void }> = [];

  if (search) {
    filterChips.push({
      id: "search",
      label: `${userCopy.searchPlaceholder}: ${search}`,
      onRemove: () => setSearchInput(""),
    });
  }
  if (
    roleFilter === UserRole.Student ||
    roleFilter === UserRole.Instructor ||
    roleFilter === UserRole.TrainingOfficeAdmin
  ) {
    filterChips.push({
      id: "role",
      label: `${userCopy.filterRole}: ${roleLabels[roleFilter]}`,
      onRemove: () => {
        setRoleFilter("");
        setCurrentPage(1);
      },
    });
  }
  if (activeFilter === "true" || activeFilter === "false") {
    filterChips.push({
      id: "active",
      label:
        activeFilter === "true"
          ? userCopy.filterActiveOnly
          : userCopy.filterInactiveOnly,
      onRemove: () => {
        setActiveFilter("");
        setCurrentPage(1);
      },
    });
  }

  return (
    <div data-testid="admin-users-page">
      <PageHeader
        title={userCopy.pageTitle}
        description={userCopy.pageDescription}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link
              to="/admin/users/import"
              className="inline-flex min-h-touch items-center justify-center rounded-md border border-border px-4 font-medium hover:bg-surface-raised"
              data-testid="user-import-link"
            >
              <Upload className="mr-2 h-4 w-4" aria-hidden="true" />
              {userCopy.importButton}
            </Link>
            <Link
              to="/admin/users/new"
              className="inline-flex min-h-touch items-center justify-center rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700"
              data-testid="create-user-link"
            >
              {userCopy.createButton}
            </Link>
          </div>
        }
      />

      <div
        className="mb-4 flex flex-col gap-3 rounded-md border border-border bg-surface-raised p-4 lg:flex-row lg:items-end"
        data-testid="user-list-toolbar"
      >
        <div className="flex-1">
          <Label htmlFor="user-search">{userCopy.searchPlaceholder}</Label>
          <div className="relative mt-1">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
              aria-hidden
            />
            <Input
              id="user-search"
              value={searchInput}
              placeholder={userCopy.searchPlaceholder}
              className="pl-10 pr-10"
              onChange={(e) => setSearchInput(e.target.value)}
              data-testid="user-list-search"
            />
            {searchInput ? (
              <button
                type="button"
                className="absolute right-2 top-1/2 flex min-h-touch min-w-touch -translate-y-1/2 items-center justify-center rounded-full text-text-secondary hover:bg-surface-muted"
                onClick={() => setSearchInput("")}
                aria-label={userCopy.clearSearch}
                data-testid="user-search-clear"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            ) : null}
          </div>
        </div>

        <div>
          <Label htmlFor="user-role-filter">{userCopy.filterRole}</Label>
          <select
            id="user-role-filter"
            className="mt-1 flex min-h-touch w-full min-w-[180px] rounded-md border border-border bg-surface px-3 text-body lg:w-auto"
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setCurrentPage(1);
            }}
            data-testid="user-role-filter"
          >
            <option value="">{userCopy.filterAllRoles}</option>
            <option value={UserRole.Student}>{roleLabels.Student}</option>
            <option value={UserRole.Instructor}>{roleLabels.Instructor}</option>
            <option value={UserRole.TrainingOfficeAdmin}>
              {roleLabels.TrainingOfficeAdmin}
            </option>
          </select>
        </div>

        <div>
          <Label htmlFor="user-active-filter">{userCopy.filterActive}</Label>
          <select
            id="user-active-filter"
            className="mt-1 flex min-h-touch w-full min-w-[180px] rounded-md border border-border bg-surface px-3 text-body lg:w-auto"
            value={activeFilter}
            onChange={(e) => {
              setActiveFilter(e.target.value);
              setCurrentPage(1);
            }}
            data-testid="user-active-filter"
          >
            <option value="">{userCopy.filterAllStatuses}</option>
            <option value="true">{userCopy.filterActiveOnly}</option>
            <option value="false">{userCopy.filterInactiveOnly}</option>
          </select>
        </div>
      </div>

      {filterChips.length > 0 ? (
        <div className="mb-4 flex flex-wrap gap-2" data-testid="user-filter-chips">
          {filterChips.map((chip) => (
            <FilterChip
              key={chip.id}
              label={chip.label}
              onRemove={chip.onRemove}
              testId={`user-filter-chip-${chip.id}`}
            />
          ))}
        </div>
      ) : null}

      {query.isLoading ? (
        <UserListTable users={[]} loading />
      ) : query.isError ? (
        <UserListTableError onRetry={() => void query.refetch()} />
      ) : sortedUsers.length === 0 ? (
        <EmptyState
          icon={Users}
          title={userCopy.emptyTitle}
          description={
            hasFilters
              ? "Không có người dùng phù hợp với bộ lọc hiện tại."
              : userCopy.emptyDescription
          }
          action={
            hasFilters ? undefined : (
              <Link
                to="/admin/users/new"
                className="inline-flex min-h-touch items-center justify-center rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700"
              >
                <Plus className="mr-2 h-4 w-4" />
                {userCopy.createButton}
              </Link>
            )
          }
        />
      ) : (
        <>
          <UserListTable
            users={pageUsers}
            sortColumn={sortColumn}
            sortDirection={sortDirection}
            onSortChange={handleSortChange}
            onUserUpdated={() => void query.refetch()}
          />
          <UserListPagination
            currentPage={currentPage}
            totalPages={totalPages}
            loading={query.isFetchingNextPage}
            onPageChange={setCurrentPage}
          />
        </>
      )}
    </div>
  );
}
