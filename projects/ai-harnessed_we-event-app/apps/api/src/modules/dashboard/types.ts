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
  /** Attended participants missing required feedback when feedbackRequired is true. */
  mandatoryFeedbackOutstanding: number;
}
