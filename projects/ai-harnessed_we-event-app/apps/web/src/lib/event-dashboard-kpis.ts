import type { KpiItem } from "@/components/layout/kpi-summary-strip";
import type { EventDashboardMetrics } from "@/lib/organizer-api";

export interface EventDashboardKpiLinks {
  registrations: string;
  waitlist: string;
  checkIn: string;
  eligibility: string;
}

export function buildEventDashboardKpiItems(
  metrics: EventDashboardMetrics,
  links: EventDashboardKpiLinks,
): KpiItem[] {
  const checkInTotal = metrics.checkedIn + metrics.attended;
  const feedbackHint = metrics.feedbackRequired
    ? metrics.mandatoryFeedbackOutstanding > 0
      ? `${metrics.mandatoryFeedbackOutstanding} mandatory outstanding`
      : "Mandatory feedback complete"
    : "Feedback optional for this event";

  return [
    {
      label: "Registrations",
      value: metrics.registrations,
      hint: "All registration records",
      href: links.registrations,
    },
    {
      label: "Waitlist",
      value: metrics.waitlist,
      hint: "FIFO queue position preserved",
      href: links.waitlist,
    },
    {
      label: "Check-ins",
      value: checkInTotal,
      hint: `${metrics.checkedIn} checked in · ${metrics.attended} attended`,
      href: links.checkIn,
    },
    {
      label: "Feedback",
      value: metrics.feedbackSubmitted,
      hint: feedbackHint,
      href: `${links.registrations}?state=Attended`,
    },
    {
      label: "Eligibility",
      value: `${metrics.eligible} eligible`,
      hint: `${metrics.notEligible} not eligible · ${metrics.pendingEligibility} pending`,
      href: links.eligibility,
    },
  ];
}

export function feedbackCompletionRatio(metrics: EventDashboardMetrics): {
  submitted: number;
  denominator: number;
  percent: number;
} {
  const denominator = metrics.attended;
  const submitted = metrics.feedbackSubmitted;
  const percent =
    denominator > 0 ? Math.round((submitted / denominator) * 100) : 0;

  return { submitted, denominator, percent };
}
