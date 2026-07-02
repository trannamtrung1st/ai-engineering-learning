import { UserRole } from "@wecheck/domain";
import { describe, expect, it } from "vitest";
import {
  normalizeUsersSearchQuery,
  paginateUsers,
  sortUsers,
  USERS_PAGE_SIZE,
  usersPageCount,
} from "@/lib/users-list-filters";
import type { UserDto } from "@/lib/users-api";

const baseUser: UserDto = {
  id: "1",
  institutionalId: "SV2026001",
  displayName: "Nguyễn Văn A",
  email: "a@example.edu.vn",
  role: UserRole.Student,
  active: true,
  createdAt: "2026-06-01T00:00:00.000Z",
};

/** AC-01 / FR-01 — admin users listing helpers */
describe("users-list-filters (AC-01, FR-01)", () => {
  it("TC-AC-01-018: normalizeUsersSearchQuery requires min 2 chars", () => {
    expect(normalizeUsersSearchQuery("a")).toBeUndefined();
    expect(normalizeUsersSearchQuery("  ab ")).toBe("ab");
  });

  it("TC-AC-01-018: sortUsers orders displayName ascending by default", () => {
    const users: UserDto[] = [
      { ...baseUser, id: "2", displayName: "Trần Thị B" },
      { ...baseUser, id: "1", displayName: "An Văn C" },
    ];
    const sorted = sortUsers(users, "displayName", "asc");
    expect(sorted[0]?.displayName).toBe("An Văn C");
    expect(sorted[1]?.displayName).toBe("Trần Thị B");
  });

  it("uses offset-25 page size constant", () => {
    expect(USERS_PAGE_SIZE).toBe(25);
  });

  it("TC-AC-01-018: paginateUsers returns page slices", () => {
    const items = Array.from({ length: 30 }, (_, i) => `user-${i}`);
    expect(paginateUsers(items, 1)).toHaveLength(25);
    expect(paginateUsers(items, 2)).toHaveLength(5);
    expect(usersPageCount(30)).toBe(2);
  });
});
