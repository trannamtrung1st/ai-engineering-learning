import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  feedbackCompletionRatio,
  type EventDashboardKpiLinks,
} from "@/lib/event-dashboard-kpis";
import type { EventDashboardMetrics } from "@/lib/organizer-api";

export interface FeedbackCompletionTrackerProps {
  metrics: EventDashboardMetrics;
  links: Pick<EventDashboardKpiLinks, "registrations">;
}

export function FeedbackCompletionTracker({
  metrics,
  links,
}: FeedbackCompletionTrackerProps) {
  const { submitted, denominator, percent } = feedbackCompletionRatio(metrics);
  const pendingHref = `${links.registrations}?state=Attended`;

  return (
    <section
      aria-label="Feedback completion"
      className="space-y-3 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
            Feedback completion
          </h2>
          <p className="mt-1 text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
            {metrics.feedbackRequired
              ? "Mandatory feedback policy is enabled for this event."
              : "Feedback is optional for this event."}
          </p>
        </div>
        {metrics.feedbackRequired && metrics.mandatoryFeedbackOutstanding > 0 ? (
          <Button asChild size="sm" variant="secondary">
            <Link href={pendingHref}>Review pending feedback</Link>
          </Button>
        ) : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
            Submitted
          </p>
          <p className="text-[length:var(--font-size-xl)] font-[var(--font-weight-semibold)]">
            {submitted}
          </p>
        </div>
        <div>
          <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
            Attended participants
          </p>
          <p className="text-[length:var(--font-size-xl)] font-[var(--font-weight-semibold)]">
            {denominator}
          </p>
        </div>
        <div>
          <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
            Completion
          </p>
          <p className="text-[length:var(--font-size-xl)] font-[var(--font-weight-semibold)]">
            {percent}%
          </p>
        </div>
      </div>

      <div
        className="h-2 overflow-hidden rounded-full bg-[var(--color-bg-subtle)]"
        role="progressbar"
        aria-valuenow={submitted}
        aria-valuemin={0}
        aria-valuemax={Math.max(denominator, 1)}
        aria-label={`${submitted} of ${denominator} attended participants submitted feedback`}
      >
        <div
          className="h-full rounded-full bg-[var(--color-status-completed-bg,var(--color-action-primary-bg))] transition-all"
          style={{
            width: `${denominator > 0 ? Math.min((submitted / denominator) * 100, 100) : 0}%`,
          }}
        />
      </div>

      {metrics.feedbackRequired && metrics.mandatoryFeedbackOutstanding > 0 ? (
        <Alert variant="warning" title="Mandatory feedback outstanding">
          {metrics.mandatoryFeedbackOutstanding} attended participant
          {metrics.mandatoryFeedbackOutstanding === 1 ? "" : "s"} still need
          to submit required feedback.
        </Alert>
      ) : null}
    </section>
  );
}
