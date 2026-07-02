import { SessionStatus } from "@wecheck/domain";
import { describe, expect, it } from "vitest";
import type { SessionListItem } from "@/lib/sessions-api";
import {
  buildSessionsListDisplayEntries,
  matchesSessionSearch,
  paginateSessionsListEntries,
  SESSIONS_LIST_PAGE_SIZE,
} from "@/lib/sessions-list-filters";

function session(
  overrides: Partial<SessionListItem> & Pick<SessionListItem, "id" | "status" | "scheduledStart">,
): SessionListItem {
  return {
    instructorId: "inst-1",
    classId: "class-1",
    subjectId: "sub-1",
    title: "Buổi học",
    roomName: "Phòng A",
    roomLatitude: 10.76,
    roomLongitude: 106.66,
    gpsRadiusMeters: 100,
    openedAt: null,
    closedAt: null,
    classCode: "HESD-01",
    className: "Hệ thống nhúng",
    subjectCode: "SWE-101",
    subjectName: "Phần mềm nhúng",
    ...overrides,
  };
}

describe("sessions-list-filters (AC-06 / TC-AC-06-021)", () => {
  it("matchesSessionSearch filters by class and subject fields", () => {
    const item = session({
      id: "s1",
      status: SessionStatus.Active,
      scheduledStart: "2026-06-30T08:00:00.000Z",
    });

    expect(matchesSessionSearch(item, "hesd")).toBe(true);
    expect(matchesSessionSearch(item, "SWE-101")).toBe(true);
    expect(matchesSessionSearch(item, "nhúng")).toBe(true);
    expect(matchesSessionSearch(item, "HESD-02")).toBe(false);
  });

  it("buildSessionsListDisplayEntries groups Active → Draft → Closed when filter is all", () => {
    const items = [
      session({
        id: "closed-1",
        status: SessionStatus.Closed,
        scheduledStart: "2026-06-28T08:00:00.000Z",
      }),
      session({
        id: "draft-1",
        status: SessionStatus.Draft,
        scheduledStart: "2026-06-29T08:00:00.000Z",
      }),
      session({
        id: "active-1",
        status: SessionStatus.Active,
        scheduledStart: "2026-06-30T08:00:00.000Z",
      }),
    ];

    const entries = buildSessionsListDisplayEntries(items, {
      search: "",
      statusFilter: "all",
      sortKey: "date",
      sectionLabels: {
        active: "Đang diễn ra",
        draft: "Nháp",
        closed: "Đã kết thúc",
      },
    });

    expect(entries.map((entry) => (entry.kind === "section" ? entry.label : entry.session.id))).toEqual(
      ["Đang diễn ra", "active-1", "Nháp", "draft-1", "Đã kết thúc", "closed-1"],
    );
  });

  it("buildSessionsListDisplayEntries keeps only Active sessions when active chip selected", () => {
    const items = [
      session({
        id: "active-1",
        status: SessionStatus.Active,
        scheduledStart: "2026-06-30T08:00:00.000Z",
      }),
      session({
        id: "draft-1",
        status: SessionStatus.Draft,
        scheduledStart: "2026-06-29T08:00:00.000Z",
      }),
    ];

    const entries = buildSessionsListDisplayEntries(items, {
      search: "",
      statusFilter: "active",
      sortKey: "date",
      sectionLabels: {
        active: "Đang diễn ra",
        draft: "Nháp",
        closed: "Đã kết thúc",
      },
    });

    expect(entries).toEqual([{ kind: "session", session: items[0] }]);
  });

  it("paginateSessionsListEntries exposes load-more when more than page size", () => {
    const entries = Array.from({ length: SESSIONS_LIST_PAGE_SIZE + 3 }, (_, index) => index);
    const page = paginateSessionsListEntries(entries, SESSIONS_LIST_PAGE_SIZE);

    expect(page.visibleEntries).toHaveLength(SESSIONS_LIST_PAGE_SIZE);
    expect(page.hasMore).toBe(true);
  });
});
