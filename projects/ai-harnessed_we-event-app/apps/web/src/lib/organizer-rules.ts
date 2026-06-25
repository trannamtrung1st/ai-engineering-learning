import type { SessionInfo } from "@/lib/participant-api";

export function isOrganizerAdmin(session: SessionInfo): boolean {
  return session.role === "OrganizerAdmin";
}

export function isOrganizerStaff(session: SessionInfo): boolean {
  return session.role === "OrganizerStaff";
}

export function canAccessEvent(session: SessionInfo, eventId: string): boolean {
  if (session.role === "OrganizerAdmin") {
    return true;
  }
  if (session.role === "OrganizerStaff") {
    return (session.assignedEventIds ?? []).includes(eventId);
  }
  return false;
}

export function filterEventsForScope<T extends { eventId: string }>(
  session: SessionInfo,
  items: T[],
): T[] {
  if (session.role === "OrganizerAdmin") {
    return items;
  }
  const assigned = new Set(session.assignedEventIds ?? []);
  return items.filter((item) => assigned.has(item.eventId));
}
