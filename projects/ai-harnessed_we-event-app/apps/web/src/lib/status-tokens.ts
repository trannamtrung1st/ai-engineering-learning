/** Maps domain status values to semantic token CSS variables. */
export type DomainStatus =
  | "registered"
  | "waitlisted"
  | "rejected"
  | "attended"
  | "absent"
  | "eligible"
  | "notEligible"
  | "pending";

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
};
