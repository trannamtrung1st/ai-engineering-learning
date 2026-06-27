import type { EventState } from "@we-event/domain";

import {
  fetchOrganizerEvent,
  fetchOrganizerEvents,
  type FetchEventsParams,
} from "@/lib/organizer-api";
import type { EventListItem, PaginatedResult, SessionInfo } from "@/lib/participant-api";

function toListItem(event: {
  eventId: string;
  name: string;
  state: EventState;
  startAt: string;
  location?: string;
}): EventListItem {
  return {
    eventId: event.eventId,
    name: event.name,
    state: event.state,
    startAt: event.startAt,
    location: event.location ?? "",
  };
}

export function matchesEventListFilters(
  event: EventListItem,
  params: FetchEventsParams,
): boolean {
  if (params.state && event.state !== params.state) {
    return false;
  }
  const query = params.q?.trim().toLowerCase();
  if (!query) {
    return true;
  }
  return (
    event.name.toLowerCase().includes(query) ||
    event.location.toLowerCase().includes(query)
  );
}

export function paginateLocally<T>(
  items: T[],
  page: number,
  pageSize: number,
): PaginatedResult<T> {
  const total = items.length;
  const totalPages = total === 0 ? 0 : Math.ceil(total / pageSize);
  const safePage = Math.max(1, page);
  const offset = (safePage - 1) * pageSize;
  return {
    items: items.slice(offset, offset + pageSize),
    page: safePage,
    pageSize,
    total,
    totalPages,
  };
}

/**
 * Staff assignments are a bounded scope — fetch assigned events and paginate locally.
 * Admins use the server-driven events list.
 */
export async function fetchScopedOrganizerEvents(
  token: string,
  session: SessionInfo,
  params: FetchEventsParams = {},
): Promise<PaginatedResult<EventListItem>> {
  const page = params.page ?? 1;
  const pageSize = params.pageSize ?? 20;

  if (session.role === "OrganizerAdmin") {
    return fetchOrganizerEvents(token, { ...params, page, pageSize });
  }

  const assignedIds = session.assignedEventIds ?? [];
  if (assignedIds.length === 0) {
    return { items: [], page, pageSize, total: 0, totalPages: 0 };
  }

  const loaded = await Promise.all(
    assignedIds.map(async (eventId) => {
      try {
        return await fetchOrganizerEvent(token, eventId);
      } catch {
        return null;
      }
    }),
  );

  const items = loaded
    .filter((event): event is NonNullable<typeof event> => event !== null)
    .map(toListItem)
    .filter((event) => matchesEventListFilters(event, params))
    .sort(
      (left, right) =>
        new Date(right.startAt).getTime() - new Date(left.startAt).getTime(),
    );

  return paginateLocally(items, page, pageSize);
}
