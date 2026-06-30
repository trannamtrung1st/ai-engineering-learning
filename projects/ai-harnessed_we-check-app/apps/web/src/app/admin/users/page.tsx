import { UserRole } from "@wecheck/domain";
import { Plus, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
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

/** FR-01 / AC-01 / NFR-11 — admin user list with search and filters */
export function AdminUsersPage() {
  const authUser = useAuthUser();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("");
  const [activeFilter, setActiveFilter] = useState<string>("");

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

  if (authUser.role !== UserRole.TrainingOfficeAdmin) {
    return <ForbiddenPage homeTo="/check-in" />;
  }

  const users = query.data?.pages.flatMap((page) => page.items) ?? [];
  const hasFilters = Boolean(search || roleFilter || activeFilter);

  function applySearch() {
    setSearch(searchInput.trim());
  }

  return (
    <div data-testid="admin-users-page">
      <PageHeader
        title={userCopy.pageTitle}
        description={userCopy.pageDescription}
        actions={
          <Link
            to="/admin/users/new"
            className="inline-flex min-h-touch items-center justify-center rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700"
            data-testid="create-user-link"
          >
            {userCopy.createButton}
          </Link>
        }
      />

      <div
        className="mb-4 flex flex-col gap-3 rounded-md border border-border bg-surface-raised p-4 lg:flex-row lg:items-end"
        data-testid="user-list-toolbar"
      >
        <div className="flex-1">
          <Label htmlFor="user-search">{userCopy.searchPlaceholder}</Label>
          <div className="mt-1 flex gap-2">
            <Input
              id="user-search"
              value={searchInput}
              placeholder={userCopy.searchPlaceholder}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") applySearch();
              }}
            />
            <Button type="button" variant="outline" onClick={applySearch}>
              Tìm
            </Button>
          </div>
        </div>

        <div>
          <Label htmlFor="user-role-filter">{userCopy.filterRole}</Label>
          <select
            id="user-role-filter"
            className="mt-1 flex min-h-touch w-full min-w-[180px] rounded-md border border-border bg-surface px-3 text-body lg:w-auto"
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
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
            onChange={(e) => setActiveFilter(e.target.value)}
          >
            <option value="">{userCopy.filterAllStatuses}</option>
            <option value="true">{userCopy.filterActiveOnly}</option>
            <option value="false">{userCopy.filterInactiveOnly}</option>
          </select>
        </div>
      </div>

      {query.isLoading ? (
        <UserListTable users={[]} loading />
      ) : query.isError ? (
        <UserListTableError onRetry={() => void query.refetch()} />
      ) : users.length === 0 ? (
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
            users={users}
            onUserUpdated={() => void query.refetch()}
          />
          {query.hasNextPage ? (
            <div className="mt-4 flex justify-center">
              <Button
                type="button"
                variant="outline"
                loading={query.isFetchingNextPage}
                data-testid="user-list-load-more"
                onClick={() => void query.fetchNextPage()}
              >
                {query.isFetchingNextPage ? userCopy.loadingMore : userCopy.loadMore}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
