"use client";

import Link from "next/link";
import { ArrowRight, ClipboardCheck, MessageSquare, ShieldCheck } from "lucide-react";

import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { EventStateBadge } from "@/components/participant/event-state-badge";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLiveQuery } from "@/hooks/use-live-query";
import { formatDateTime } from "@/lib/format";
import { fetchMyRegistrations } from "@/lib/participant-api";
import {
  canSelfCheckIn,
  canSubmitFeedback,
  canViewEligibility,
} from "@/lib/participant-rules";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/providers/auth-provider";

export default function MyRegistrationsPage() {
  const { token } = useAuth();

  const registrationsQuery = useLiveQuery({
    queryKey: queryKeys.registrations.mine(),
    queryFn: () => fetchMyRegistrations(token!),
    mode: "eventList",
    enabled: Boolean(token),
  });

  const entries = registrationsQuery.data ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        title="My registrations"
        subtitle="Current and past registrations with quick access to check-in and feedback."
      />

      {registrationsQuery.isLoading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-36 w-full" />
          ))}
        </div>
      ) : null}

      {registrationsQuery.isError ? (
        <EmptyFailureBlock
          variant="failure"
          title="Could not load registrations"
          description={registrationsQuery.error.message}
          actionLabel="Retry"
          onAction={() => void registrationsQuery.refetch()}
        />
      ) : null}

      {registrationsQuery.isSuccess && entries.length === 0 ? (
        <EmptyFailureBlock
          variant="empty"
          title="No registrations yet"
          description="Browse published events and register when registration is open."
          actionLabel="Browse events"
          onAction={() => {
            window.location.href = "/events";
          }}
        />
      ) : null}

      {entries.length > 0 ? (
        <ul className="space-y-4">
          {entries.map(({ event, registration }) => (
            <li
              key={registration.registrationId}
              className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1">
                  <Link
                    href={`/events/${event.eventId}`}
                    className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)]"
                  >
                    {event.name}
                  </Link>
                  <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                    {formatDateTime(event.startAt)}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <EventStateBadge state={event.state} />
                  <RegistrationStateBadge state={registration.state} />
                </div>
              </div>

              {registration.waitlistPosition ? (
                <p className="mt-3 text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                  Waitlist position {registration.waitlistPosition}
                </p>
              ) : null}

              {registration.reasonText ? (
                <p className="mt-3 text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                  {registration.reasonText}
                </p>
              ) : null}

              <div className="mt-4 flex flex-wrap gap-2">
                {canSelfCheckIn(
                  event.state,
                  registration.state,
                  event.ruleConfig.checkinOpenAt,
                  event.ruleConfig.checkinCloseAt,
                ) ? (
                  <Button asChild size="sm" variant="secondary">
                    <Link href={`/events/${event.eventId}/check-in`}>
                      <ClipboardCheck className="h-4 w-4" aria-hidden />
                      Check in
                    </Link>
                  </Button>
                ) : null}

                {canSubmitFeedback(
                  event.state,
                  registration.state,
                  event.ruleConfig.feedbackOpenAt,
                  event.ruleConfig.feedbackCloseAt,
                ) ? (
                  <Button asChild size="sm" variant="secondary">
                    <Link href={`/events/${event.eventId}/feedback`}>
                      <MessageSquare className="h-4 w-4" aria-hidden />
                      Feedback
                    </Link>
                  </Button>
                ) : null}

                {canViewEligibility(event.state, registration.state) ? (
                  <Button asChild size="sm" variant="ghost">
                    <Link href={`/events/${event.eventId}/eligibility`}>
                      <ShieldCheck className="h-4 w-4" aria-hidden />
                      Eligibility
                    </Link>
                  </Button>
                ) : null}

                <Button asChild size="sm" variant="ghost">
                  <Link href={`/events/${event.eventId}`}>
                    Event details
                    <ArrowRight className="h-4 w-4" aria-hidden />
                  </Link>
                </Button>
              </div>

              <p className="mt-3 text-[length:var(--font-size-xs)] text-[var(--color-text-secondary)]">
                Updated {formatDateTime(registration.updatedAt)}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
