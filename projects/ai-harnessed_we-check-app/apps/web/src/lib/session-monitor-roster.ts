import { AttendanceStatus } from "@wecheck/domain";
import type { SessionMonitorRecord } from "@/lib/session-monitor-api";

export type MonitorStatusFilter = "all" | (typeof AttendanceStatus)[keyof typeof AttendanceStatus];

/** AC-15b / listing-pages §5.3 — instructor priority: Chờ → Vắng → Có mặt → Có phép */
export const STATUS_SORT_ORDER: Record<string, number> = {
  [AttendanceStatus.Pending]: 0,
  [AttendanceStatus.Absent]: 1,
  [AttendanceStatus.Present]: 2,
  [AttendanceStatus.Excused]: 3,
  [AttendanceStatus.Rejected]: 4,
};

export type MonitorSortColumn = "displayName" | "status";
export type MonitorSortDirection = "asc" | "desc";

export function filterMonitorRecords(
  records: SessionMonitorRecord[],
  filter: MonitorStatusFilter,
): SessionMonitorRecord[] {
  if (filter === "all") return records;
  return records.filter((record) => record.status === filter);
}

/** 14-listing §3.2 — client search on displayName and institutionalId */
export function searchMonitorRecords(
  records: SessionMonitorRecord[],
  rawQuery: string,
): SessionMonitorRecord[] {
  const query = rawQuery.trim().toLocaleLowerCase("vi");
  if (!query) return records;

  return records.filter((record) => {
    const haystack = [record.displayName, record.institutionalId]
      .join(" ")
      .toLocaleLowerCase("vi");
    return haystack.includes(query);
  });
}

export function sortMonitorRecords(
  records: SessionMonitorRecord[],
  column: MonitorSortColumn | null,
  direction: MonitorSortDirection,
): SessionMonitorRecord[] {
  const sorted = [...records].sort((a, b) => {
    let cmp = 0;
    if (column === "status") {
      cmp = STATUS_SORT_ORDER[a.status] - STATUS_SORT_ORDER[b.status];
      if (cmp === 0) {
        cmp = a.displayName.localeCompare(b.displayName, "vi");
      }
    } else if (column === "displayName") {
      cmp = a.displayName.localeCompare(b.displayName, "vi");
    } else {
      cmp = STATUS_SORT_ORDER[a.status] - STATUS_SORT_ORDER[b.status];
      if (cmp === 0) {
        cmp = a.displayName.localeCompare(b.displayName, "vi");
      }
    }
    return direction === "asc" ? cmp : -cmp;
  });
  return sorted;
}

export function formatMonitorTimestamp(iso: string): string {
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(iso));
}

export function formatPollTime(updatedAtMs: number): string {
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(updatedAtMs));
}
