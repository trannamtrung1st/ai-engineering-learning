import type { UserRole } from "@wecheck/domain";
import type { UserDto } from "@/lib/users-api";

export type UsersSortColumn = "displayName" | "institutionalId" | "email" | "role";

export type UsersSortDirection = "asc" | "desc";

export const USERS_PAGE_SIZE = 25;

const collator = new Intl.Collator("vi", { sensitivity: "base" });

/** AC-01 / FR-01 — client-side sort for admin user table (§14-listing §5.2) */
export function sortUsers(
  users: UserDto[],
  column: UsersSortColumn,
  direction: UsersSortDirection,
): UserDto[] {
  const sorted = [...users].sort((a, b) => {
    let cmp = 0;
    switch (column) {
      case "displayName":
        cmp = collator.compare(a.displayName, b.displayName);
        break;
      case "institutionalId":
        cmp = collator.compare(a.institutionalId, b.institutionalId);
        break;
      case "email":
        cmp = collator.compare(a.email, b.email);
        break;
      case "role":
        cmp = collator.compare(a.role, b.role);
        break;
    }
    return direction === "asc" ? cmp : -cmp;
  });
  return sorted;
}

export function nextUsersSortDirection(
  column: UsersSortColumn,
  currentColumn: UsersSortColumn,
  currentDirection: UsersSortDirection,
): UsersSortDirection {
  if (column !== currentColumn) return "asc";
  return currentDirection === "asc" ? "desc" : "asc";
}

export function normalizeUsersSearchQuery(input: string): string | undefined {
  const trimmed = input.trim();
  if (trimmed.length < 2) return undefined;
  return trimmed;
}

export function roleFilterLabel(role: UserRole, labels: Record<UserRole, string>): string {
  return labels[role];
}

const SORT_COLUMNS = new Set<UsersSortColumn>([
  "displayName",
  "institutionalId",
  "email",
  "role",
]);

export function parseUsersSortColumn(value: string | null): UsersSortColumn {
  if (value && SORT_COLUMNS.has(value as UsersSortColumn)) {
    return value as UsersSortColumn;
  }
  return "displayName";
}

export function parseUsersSortDirection(value: string | null): UsersSortDirection {
  return value === "desc" ? "desc" : "asc";
}

export function paginateUsers<T>(items: T[], page: number, pageSize = USERS_PAGE_SIZE): T[] {
  const start = (page - 1) * pageSize;
  return items.slice(start, start + pageSize);
}

export function usersPageCount(totalItems: number, pageSize = USERS_PAGE_SIZE): number {
  return Math.max(1, Math.ceil(totalItems / pageSize));
}
