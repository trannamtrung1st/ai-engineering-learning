import type {
  CertificateEligibilityState,
  EventState,
  RegistrationState,
} from "@we-event/domain";

import { type DomainStatus } from "@/lib/status-tokens";

export interface StateLabel {
  label: string;
  hint?: string;
  badgeStatus?: DomainStatus;
}

export function eventStateLabel(state: EventState): StateLabel {
  switch (state) {
    case "Draft":
      return { label: "Draft", badgeStatus: "draft", hint: "Not yet visible to participants." };
    case "Published":
      return { label: "Published", badgeStatus: "published", hint: "Registration has not opened yet." };
    case "RegistrationOpen":
      return { label: "Registration open", badgeStatus: "registrationOpen", hint: "You can register now." };
    case "RegistrationClosed":
      return { label: "Registration closed", badgeStatus: "registrationClosed", hint: "Check-in opens at the scheduled time." };
    case "InProgress":
      return { label: "In progress", badgeStatus: "inProgress", hint: "The event is underway." };
    case "Completed":
      return { label: "Completed", badgeStatus: "completed", hint: "Feedback and eligibility may be available." };
    case "Archived":
      return { label: "Archived", badgeStatus: "archived", hint: "This event is read-only." };
    case "Cancelled":
      return { label: "Cancelled", badgeStatus: "cancelledEvent", hint: "This event will not take place." };
  }
}

export function registrationStateLabel(state: RegistrationState): StateLabel {
  switch (state) {
    case "Requested":
      return { label: "Requested", badgeStatus: "pending", hint: "Awaiting confirmation." };
    case "Registered":
      return { label: "Registered", badgeStatus: "registered", hint: "Your seat is confirmed." };
    case "Waitlisted":
      return { label: "Waitlisted", badgeStatus: "waitlisted", hint: "You are in the queue." };
    case "Rejected":
      return { label: "Rejected", badgeStatus: "rejected", hint: "Registration was not accepted." };
    case "CancelledByUser":
      return { label: "Cancelled by you", badgeStatus: "cancelled", hint: "You cancelled this registration." };
    case "CancelledByOrganizer":
      return { label: "Cancelled by organizer", badgeStatus: "cancelled", hint: "The organizer cancelled your registration." };
    case "CheckedIn":
      return { label: "Checked in", badgeStatus: "attended", hint: "Attendance will be finalized after the event." };
    case "Attended":
      return { label: "Attended", badgeStatus: "attended", hint: "You may submit feedback when the window opens." };
    case "Absent":
      return { label: "Absent", badgeStatus: "absent", hint: "No check-in was recorded." };
    case "Expired":
      return { label: "Expired", badgeStatus: "cancelled", hint: "Waitlist entry expired when registration closed." };
  }
}

export function eligibilityStateLabel(state: CertificateEligibilityState): StateLabel {
  switch (state) {
    case "PendingEvaluation":
      return { label: "Pending evaluation", badgeStatus: "pending", hint: "Eligibility will be evaluated soon." };
    case "Eligible":
      return { label: "Eligible", badgeStatus: "eligible", hint: "You meet certificate requirements." };
    case "NotEligible":
      return { label: "Not eligible", badgeStatus: "notEligible", hint: "Certificate requirements were not met." };
    case "Revoked":
      return { label: "Revoked", badgeStatus: "rejected", hint: "Eligibility was revoked by an organizer." };
  }
}
