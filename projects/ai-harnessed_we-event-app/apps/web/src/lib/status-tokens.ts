/** Maps domain status values to semantic token CSS variables. */
export type DomainStatus =
  | "registered"
  | "waitlisted"
  | "rejected"
  | "attended"
  | "absent"
  | "eligible"
  | "notEligible"
  | "pending"
  | "cancelled"
  | "draft"
  | "published"
  | "registrationOpen"
  | "registrationClosed"
  | "inProgress"
  | "completed"
  | "archived"
  | "cancelledEvent";

export const statusTokenMap: Record<
  DomainStatus,
  { bg: string; fg: string; label: string }
> = {
  registered: {
    bg: "var(--color-status-registered)",
    fg: "var(--color-status-registered-fg)",
    label: "Registered",
  },
  waitlisted: {
    bg: "var(--color-status-waitlisted)",
    fg: "var(--color-status-waitlisted-fg)",
    label: "Waitlisted",
  },
  rejected: {
    bg: "var(--color-status-rejected)",
    fg: "var(--color-status-rejected-fg)",
    label: "Rejected",
  },
  attended: {
    bg: "var(--color-status-attended)",
    fg: "var(--color-status-attended-fg)",
    label: "Attended",
  },
  absent: {
    bg: "var(--color-status-absent)",
    fg: "var(--color-status-absent-fg)",
    label: "Absent",
  },
  eligible: {
    bg: "var(--color-status-eligible)",
    fg: "var(--color-status-eligible-fg)",
    label: "Eligible",
  },
  notEligible: {
    bg: "var(--color-status-not-eligible)",
    fg: "var(--color-status-not-eligible-fg)",
    label: "Not eligible",
  },
  pending: {
    bg: "var(--color-status-pending)",
    fg: "var(--color-status-pending-fg)",
    label: "Pending",
  },
  cancelled: {
    bg: "var(--color-status-cancelled)",
    fg: "var(--color-status-cancelled-fg)",
    label: "Cancelled",
  },
  draft: {
    bg: "var(--color-status-draft)",
    fg: "var(--color-status-draft-fg)",
    label: "Draft",
  },
  published: {
    bg: "var(--color-status-published)",
    fg: "var(--color-status-published-fg)",
    label: "Published",
  },
  registrationOpen: {
    bg: "var(--color-status-registration-open)",
    fg: "var(--color-status-registration-open-fg)",
    label: "Registration open",
  },
  registrationClosed: {
    bg: "var(--color-status-registration-closed)",
    fg: "var(--color-status-registration-closed-fg)",
    label: "Registration closed",
  },
  inProgress: {
    bg: "var(--color-status-in-progress)",
    fg: "var(--color-status-in-progress-fg)",
    label: "In progress",
  },
  completed: {
    bg: "var(--color-status-completed)",
    fg: "var(--color-status-completed-fg)",
    label: "Completed",
  },
  archived: {
    bg: "var(--color-status-archived)",
    fg: "var(--color-status-archived-fg)",
    label: "Archived",
  },
  cancelledEvent: {
    bg: "var(--color-status-cancelled-event)",
    fg: "var(--color-status-cancelled-event-fg)",
    label: "Event cancelled",
  },
};

/** Every semantic status token declared in globals.css must have a map entry. */
export const allDomainStatuses = Object.keys(statusTokenMap) as DomainStatus[];
