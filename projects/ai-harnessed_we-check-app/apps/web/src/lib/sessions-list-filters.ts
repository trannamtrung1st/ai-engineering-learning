import { SessionStatus } from "@wecheck/domain";
import type { SessionListItem } from "@/lib/sessions-api";

export const SESSIONS_LIST_PAGE_SIZE = 20;

export type SessionsStatusFilter = "all" | "active" | "draft" | "closed";
export type SessionsSortKey = "date" | "class" | "subject";

export type SessionsListDisplayEntry =
  | { kind: "section"; label: string }
  | { kind: "session"; session: SessionListItem };

function normalizeSearch(value: string): string {
  return value.trim().toLocaleLowerCase("vi");
}

/** AC-06 / TC-AC-06-021 — client search across class and subject fields */
export function matchesSessionSearch(
  session: SessionListItem,
  rawQuery: string,
): boolean {
  const query = normalizeSearch(rawQuery);
  if (!query) return true;

  const haystack = [
    session.classCode,
    session.className,
    session.subjectCode,
    session.subjectName,
    session.title,
  ]
    .join(" ")
    .toLocaleLowerCase("vi");

  return haystack.includes(query);
}

function matchesStatusFilter(
  session: SessionListItem,
  statusFilter: SessionsStatusFilter,
): boolean {
  switch (statusFilter) {
    case "all":
      return true;
    case "active":
      return session.status === SessionStatus.Active;
    case "draft":
      return session.status === SessionStatus.Draft;
    case "closed":
      return (
        session.status === SessionStatus.Closed ||
        session.status === SessionStatus.Cancelled
      );
  }
}

function compareSessions(a: SessionListItem, b: SessionListItem, sortKey: SessionsSortKey): number {
  switch (sortKey) {
    case "class":
      return a.classCode.localeCompare(b.classCode, "vi") || compareSessions(a, b, "date");
    case "subject":
      return (
        a.subjectCode.localeCompare(b.subjectCode, "vi") ||
        compareSessions(a, b, "date")
      );
    case "date":
    default:
      return (
        new Date(b.scheduledStart).getTime() - new Date(a.scheduledStart).getTime()
      );
  }
}

function sortSessions(items: SessionListItem[], sortKey: SessionsSortKey): SessionListItem[] {
  return [...items].sort((a, b) => compareSessions(a, b, sortKey));
}

function groupByStatus(items: SessionListItem[]): {
  active: SessionListItem[];
  draft: SessionListItem[];
  closed: SessionListItem[];
} {
  return {
    active: items.filter((s) => s.status === SessionStatus.Active),
    draft: items.filter((s) => s.status === SessionStatus.Draft),
    closed: items.filter(
      (s) => s.status === SessionStatus.Closed || s.status === SessionStatus.Cancelled,
    ),
  };
}

export function buildSessionsListDisplayEntries(
  items: SessionListItem[],
  options: {
    search: string;
    statusFilter: SessionsStatusFilter;
    sortKey: SessionsSortKey;
    sectionLabels: {
      active: string;
      draft: string;
      closed: string;
    };
  },
): SessionsListDisplayEntry[] {
  const filtered = items.filter(
    (session) =>
      matchesSessionSearch(session, options.search) &&
      matchesStatusFilter(session, options.statusFilter),
  );

  if (options.statusFilter === "all") {
    const grouped = groupByStatus(filtered);
    const entries: SessionsListDisplayEntry[] = [];

    const sections: Array<{ label: string; sessions: SessionListItem[] }> = [
      { label: options.sectionLabels.active, sessions: grouped.active },
      { label: options.sectionLabels.draft, sessions: grouped.draft },
      { label: options.sectionLabels.closed, sessions: grouped.closed },
    ];

    for (const section of sections) {
      const sorted = sortSessions(section.sessions, options.sortKey);
      if (sorted.length === 0) continue;
      entries.push({ kind: "section", label: section.label });
      for (const session of sorted) {
        entries.push({ kind: "session", session });
      }
    }

    return entries;
  }

  return sortSessions(filtered, options.sortKey).map((session) => ({
    kind: "session" as const,
    session,
  }));
}

export function paginateSessionsListEntries<T>(
  entries: T[],
  visibleCount: number,
): { visibleEntries: T[]; hasMore: boolean } {
  return {
    visibleEntries: entries.slice(0, visibleCount),
    hasMore: entries.length > visibleCount,
  };
}
