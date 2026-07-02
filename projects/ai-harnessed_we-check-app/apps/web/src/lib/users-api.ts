import type { UserRole } from "@wecheck/domain";
import { apiFetch, type ApiErrorBody, type ApiErrorDetail } from "@/lib/api-client";

export interface UserDto {
  id: string;
  institutionalId: string;
  displayName: string;
  email: string;
  role: UserRole;
  active: boolean;
  createdAt: string;
}

export interface UsersListResponse {
  items: UserDto[];
  nextCursor: string | null;
}

export interface ListUsersParams {
  role?: UserRole;
  active?: boolean;
  search?: string;
  limit?: number;
  cursor?: string;
}

export interface CreateUserPayload {
  institutionalId: string;
  displayName: string;
  email: string;
  password: string;
  role: UserRole;
  active?: boolean;
}

export interface UpdateUserPayload {
  institutionalId?: string;
  displayName?: string;
  email?: string;
  password?: string;
  role?: UserRole;
  active?: boolean;
}

export type UserMutationResult =
  | { ok: true; data: UserDto }
  | { ok: false; status: number; error: ApiErrorBody };

function buildUsersQuery(params: ListUsersParams): string {
  const qs = new URLSearchParams();
  if (params.role) qs.set("role", params.role);
  if (params.active !== undefined) qs.set("active", String(params.active));
  if (params.search) qs.set("search", params.search);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.cursor) qs.set("cursor", params.cursor);
  const query = qs.toString();
  return query ? `?${query}` : "";
}

export function mapApiDetailsToFieldErrors(
  details?: ApiErrorDetail[],
): Record<string, string> {
  if (!details?.length) return {};
  const map: Record<string, string> = {};
  for (const detail of details) {
    map[detail.field] = detail.message;
  }
  return map;
}

/** FR-01 / AC-01 — list users with cursor pagination */
export async function fetchUsers(
  params: ListUsersParams = {},
): Promise<
  | { ok: true; data: UsersListResponse }
  | { ok: false; status: number; error: ApiErrorBody }
> {
  const res = await apiFetch<UsersListResponse>(`/users${buildUsersQuery(params)}`);
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}

const USERS_LIST_PAGE_SIZE = 50;

/** Paginate all users and collect institutional IDs for import preview (AC-01). */
export async function fetchAllInstitutionalIds(): Promise<
  | { ok: true; data: Set<string> }
  | { ok: false; status: number; error: ApiErrorBody }
> {
  const ids = new Set<string>();
  let cursor: string | undefined;

  do {
    const result = await fetchUsers({ limit: USERS_LIST_PAGE_SIZE, cursor });
    if (!result.ok) {
      return { ok: false, status: result.status, error: result.error };
    }
    for (const user of result.data.items) {
      ids.add(user.institutionalId);
    }
    cursor = result.data.nextCursor ?? undefined;
  } while (cursor);

  return { ok: true, data: ids };
}

/** Resolve a user by id from paginated list (no GET /users/:id on API). */
export async function fetchUserById(userId: string): Promise<UserDto | null> {
  let cursor: string | undefined;
  do {
    const result = await fetchUsers({ limit: USERS_LIST_PAGE_SIZE, cursor });
    if (!result.ok) return null;
    const match = result.data.items.find((item) => item.id === userId);
    if (match) return match;
    cursor = result.data.nextCursor ?? undefined;
  } while (cursor);
  return null;
}

export async function createUser(payload: CreateUserPayload): Promise<UserMutationResult> {
  const res = await apiFetch<UserDto>("/users", {
    method: "POST",
    body: JSON.stringify({ ...payload, active: payload.active ?? true }),
  });
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}

export async function updateUser(
  userId: string,
  payload: UpdateUserPayload,
): Promise<UserMutationResult> {
  const res = await apiFetch<UserDto>(`/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}

/** Async duplicate check for institutionalId / email on blur (FR-01). */
export async function checkUserFieldDuplicate(
  field: "institutionalId" | "email",
  value: string,
  excludeUserId?: string,
): Promise<string | null> {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const result = await fetchUsers({ search: trimmed, limit: 20 });
  if (!result.ok) return null;

  const normalizedEmail = trimmed.toLowerCase();
  const duplicate = result.data.items.find((user) => {
    if (excludeUserId && user.id === excludeUserId) return false;
    if (field === "institutionalId") {
      return user.institutionalId.toLowerCase() === trimmed.toLowerCase();
    }
    return user.email.toLowerCase() === normalizedEmail;
  });

  if (!duplicate) return null;
  return field === "email" ? "Email đã tồn tại" : "Mã định danh đã tồn tại";
}
