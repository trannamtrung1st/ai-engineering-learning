import { useInfiniteQuery } from "@tanstack/react-query";
import type { UserRole } from "@wecheck/domain";
import { fetchUsers } from "@/lib/users-api";

export interface UsersListFilters {
  role?: UserRole;
  active?: boolean;
  search?: string;
}

/** FR-01 / AC-01 — admin user directory with cursor pagination */
export function useUsersList(filters: UsersListFilters) {
  return useInfiniteQuery({
    queryKey: ["users", filters],
    queryFn: async ({ pageParam }) => {
      const result = await fetchUsers({
        role: filters.role,
        active: filters.active,
        search: filters.search || undefined,
        limit: 50,
        cursor: pageParam as string | undefined,
      });
      if (!result.ok) {
        throw new Error(result.error.errorCode ?? "UsersFetchFailed");
      }
      return result.data;
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
