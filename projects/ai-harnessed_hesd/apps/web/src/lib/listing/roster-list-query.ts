import type { RosterRow } from "../api/roster-api.js";

export type RosterSortField = "status" | "checkInTime";

export interface RosterListQueryState {
  search?: string;
  status?: string;
  attemptOutcome?: string;
  sortBy: RosterSortField;
  sortOrder: "asc" | "desc";
}

export const DEFAULT_ROSTER_LIST_QUERY: RosterListQueryState = {
  sortBy: "status",
  sortOrder: "asc",
};

const CHECKED_IN = new Set(["Present", "Late", "Manual Present"]);
const REJECTED_OUTCOMES = new Set([
  "ExpiredQr",
  "NotEnrolled",
  "DuplicateCheckIn",
  "GpsDisabled",
  "GpsRequired",
  "OutOfRadius",
  "LowAccuracy",
  "SessionNotOpen",
  "SessionClosed",
]);

function rosterGroupRank(row: RosterRow): number {
  if (CHECKED_IN.has(row.attendanceStatus)) return 0;
  if (row.attendanceStatus === "Pending") {
    return row.latestAttemptOutcome && REJECTED_OUTCOMES.has(row.latestAttemptOutcome) ? 1 : 2;
  }
  if (row.attendanceStatus === "Absent") return 3;
  if (row.attendanceStatus === "Excused") return 4;
  return 5;
}

function matchesSearch(row: RosterRow, search?: string): boolean {
  if (!search) return true;
  const needle = search.trim().toLowerCase();
  if (!needle) return true;
  return (
    row.studentCode.toLowerCase().includes(needle) ||
    row.displayName.toLowerCase().includes(needle)
  );
}

export function filterAndSortRosterRows(
  rows: RosterRow[],
  query: RosterListQueryState,
): RosterRow[] {
  const filtered = rows.filter((row) => {
    if (!matchesSearch(row, query.search)) return false;
    if (query.status && row.attendanceStatus !== query.status) return false;
    if (query.attemptOutcome) {
      if (row.latestAttemptOutcome !== query.attemptOutcome) return false;
    }
    return true;
  });

  return [...filtered].sort((a, b) => {
    const groupDiff = rosterGroupRank(a) - rosterGroupRank(b);
    if (groupDiff !== 0) return groupDiff;

    if (query.sortBy === "checkInTime") {
      const aTime = a.checkInAt ? new Date(a.checkInAt).getTime() : 0;
      const bTime = b.checkInAt ? new Date(b.checkInAt).getTime() : 0;
      return query.sortOrder === "asc" ? aTime - bTime : bTime - aTime;
    }

    const nameCmp = a.displayName.localeCompare(b.displayName, "vi");
    return query.sortOrder === "asc" ? nameCmp : -nameCmp;
  });
}

export function parseRosterListQuery(searchParams: URLSearchParams): RosterListQueryState {
  const sortBy = searchParams.get("sortBy");
  const sortOrder = searchParams.get("sortOrder");
  return {
    search: searchParams.get("search") || undefined,
    status: searchParams.get("status") || undefined,
    attemptOutcome: searchParams.get("attemptOutcome") || undefined,
    sortBy: sortBy === "checkInTime" ? "checkInTime" : "status",
    sortOrder: sortOrder === "desc" ? "desc" : "asc",
  };
}

export function rosterListQueryToSearchParams(query: RosterListQueryState): URLSearchParams {
  const params = new URLSearchParams();
  if (query.search) params.set("search", query.search);
  if (query.status) params.set("status", query.status);
  if (query.attemptOutcome) params.set("attemptOutcome", query.attemptOutcome);
  if (query.sortBy !== DEFAULT_ROSTER_LIST_QUERY.sortBy) {
    params.set("sortBy", query.sortBy);
  }
  if (query.sortOrder !== DEFAULT_ROSTER_LIST_QUERY.sortOrder) {
    params.set("sortOrder", query.sortOrder);
  }
  return params;
}
