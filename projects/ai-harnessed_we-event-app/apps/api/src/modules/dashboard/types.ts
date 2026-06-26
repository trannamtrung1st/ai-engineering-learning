export interface EventDashboardSummary {
  eventId: string;
  capacity: number;
  registrations: number;
  registeredSeats: number;
  waitlist: number;
  checkedIn: number;
  attended: number;
  eligible: number;
  notEligible: number;
  pendingEligibility: number;
  feedbackSubmitted: number;
  feedbackRequired: boolean;
}
