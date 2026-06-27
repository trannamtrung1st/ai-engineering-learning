"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { EligibilityStateBadge } from "@/components/participant/eligibility-state-badge";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLiveQuery } from "@/hooks/use-live-query";
import { eligibilityStateLabel } from "@/lib/domain-labels";
import { formatDateTime } from "@/lib/format";
import { fetchEvent, fetchMyEligibility } from "@/lib/participant-api";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/providers/auth-provider";

export default function EligibilityPage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;
  const { token } = useAuth();

  const eventQuery = useLiveQuery({
    queryKey: queryKeys.events.detail(eventId),
    queryFn: () => fetchEvent(token!, eventId),
    mode: "eventList",
    enabled: Boolean(token),
  });

  const eligibilityQuery = useLiveQuery({
    queryKey: queryKeys.eligibility.me(eventId),
    queryFn: () => fetchMyEligibility(token!, eventId),
    mode: "eventList",
    enabled: Boolean(token),
  });

  const event = eventQuery.data;
  const eligibility = eligibilityQuery.data;
  const eligibilityLabel = eligibility
    ? eligibilityStateLabel(eligibility.result)
    : null;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Certificate eligibility"
        subtitle={
          event
            ? `Eligibility outcome for ${event.name} based on attendance and feedback.`
            : "Your eligibility evaluation result."
        }
        actions={
          <Button asChild variant="ghost" size="sm">
            <Link href={`/events/${eventId}`}>Back to event</Link>
          </Button>
        }
      />

      {eventQuery.isLoading || eligibilityQuery.isLoading ? (
        <Skeleton className="h-48 w-full max-w-xl" />
      ) : null}

      {eventQuery.isError ? (
        <EmptyFailureBlock
          variant="failure"
          title="Could not load event"
          description={eventQuery.error.message}
          actionLabel="Back to events"
          onAction={() => {
            window.location.href = "/events";
          }}
        />
      ) : null}

      {eligibilityQuery.isError ? (
        <EmptyFailureBlock
          variant="failure"
          title="Could not evaluate eligibility"
          description={eligibilityQuery.error.message}
          actionLabel="Retry"
          onAction={() => void eligibilityQuery.refetch()}
        />
      ) : null}

      {eligibility ? (
        <div className="max-w-xl space-y-4 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6">
          <EligibilityStateBadge state={eligibility.result} />

          {eligibilityLabel?.hint ? (
            <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
              {eligibilityLabel.hint}
            </p>
          ) : null}

          {eligibility.reasonText ? (
            <Alert
              variant={eligibility.result === "Eligible" ? "success" : "warning"}
              title={eligibility.reasonCode ?? "Evaluation reason"}
            >
              {eligibility.reasonText}
            </Alert>
          ) : null}

          <dl className="grid gap-3 text-[length:var(--font-size-sm)]">
            <div>
              <dt className="text-[var(--color-text-secondary)]">Evaluated at</dt>
              <dd className="font-[var(--font-weight-medium)]">
                {formatDateTime(eligibility.evaluatedAt)}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--color-text-secondary)]">Last updated</dt>
              <dd className="font-[var(--font-weight-medium)]">
                {formatDateTime(eligibility.updatedAt)}
              </dd>
            </div>
          </dl>
        </div>
      ) : null}
    </div>
  );
}
