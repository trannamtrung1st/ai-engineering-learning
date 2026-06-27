"use client";

import { useParams } from "next/navigation";
import { Calendar, MapPin } from "lucide-react";

import { EventCoverMedia } from "@/components/participant/event-cover-media";
import { EventStateBadge } from "@/components/participant/event-state-badge";
import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Alert } from "@/components/ui/alert";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { useLiveQuery } from "@/hooks/use-live-query";
import { ApiClientError } from "@/lib/api-client";
import {
  eventStateLabel,
  registrationStateLabel,
} from "@/lib/domain-labels";
import { formatDateTime } from "@/lib/format";
import { fetchEvent, fetchRegistrationStatus } from "@/lib/participant-api";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/providers/auth-provider";

export default function EventDetailPage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;
  const { token } = useAuth();

  const eventQuery = useLiveQuery({
    queryKey: queryKeys.events.detail(eventId),
    queryFn: () => fetchEvent(token!, eventId),
    mode: "eventList",
    enabled: Boolean(token),
  });

  const registrationQuery = useLiveQuery({
    queryKey: queryKeys.registrations.status(eventId),
    queryFn: () => fetchRegistrationStatus(token!, eventId),
    mode: "eventList",
    enabled: Boolean(token),
  });

  const event = eventQuery.data;
  const registration = registrationQuery.data?.registration ?? null;
  const eventLabel = event ? eventStateLabel(event.state) : null;
  const registrationLabel = registration
    ? registrationStateLabel(registration.state)
    : null;

  return (
    <div className="space-y-8">
      {eventQuery.isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-10 w-2/3" />
          <Skeleton className="aspect-[21/9] w-full" />
          <SkeletonText lines={4} />
        </div>
      ) : null}

      {eventQuery.isError ? (
        <EmptyFailureBlock
          variant="failure"
          title="Could not load event"
          description={
            eventQuery.error instanceof ApiClientError && eventQuery.error.status === 404
              ? "This event is not available or does not exist."
              : eventQuery.error.message
          }
          actionLabel="Back to events"
          onAction={() => {
            window.location.href = "/events";
          }}
        />
      ) : null}

      {event ? (
        <>
          <PageHeader
            title={event.name}
            subtitle={event.description || "Event details and operational windows."}
            actions={<EventStateBadge state={event.state} />}
          />

          <EventCoverMedia
            coverImageUrl={event.coverImageUrl}
            alt={`Cover image for ${event.name}`}
            variant="hero"
          />

          <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
            <section className="space-y-6 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6">
              <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
                Event information
              </h2>
              <dl className="grid gap-4 sm:grid-cols-2">
                <div className="flex gap-2">
                  <Calendar className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-text-secondary)]" aria-hidden />
                  <div>
                    <dt className="text-[length:var(--font-size-xs)] text-[var(--color-text-secondary)]">
                      Schedule
                    </dt>
                    <dd className="text-[length:var(--font-size-sm)] font-[var(--font-weight-medium)]">
                      {formatDateTime(event.startAt)} – {formatDateTime(event.endAt)}
                    </dd>
                  </div>
                </div>
                {event.location ? (
                  <div className="flex gap-2">
                    <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-text-secondary)]" aria-hidden />
                    <div>
                      <dt className="text-[length:var(--font-size-xs)] text-[var(--color-text-secondary)]">
                        Location
                      </dt>
                      <dd className="text-[length:var(--font-size-sm)] font-[var(--font-weight-medium)]">
                        {event.location}
                      </dd>
                    </div>
                  </div>
                ) : null}
              </dl>

              {eventLabel?.hint ? (
                <Alert variant="info" title="Event status">
                  {eventLabel.hint}
                </Alert>
              ) : null}

              <div className="space-y-3 border-t border-[var(--color-border-default)] pt-4">
                <h3 className="text-[length:var(--font-size-sm)] font-[var(--font-weight-semibold)]">
                  Operational windows
                </h3>
                <dl className="grid gap-3 text-[length:var(--font-size-sm)] sm:grid-cols-2">
                  <div>
                    <dt className="text-[var(--color-text-secondary)]">Registration</dt>
                    <dd>{formatDateTime(event.ruleConfig.registrationOpenAt)} – {formatDateTime(event.ruleConfig.registrationCloseAt)}</dd>
                  </div>
                  <div>
                    <dt className="text-[var(--color-text-secondary)]">Check-in</dt>
                    <dd>{formatDateTime(event.ruleConfig.checkinOpenAt)} – {formatDateTime(event.ruleConfig.checkinCloseAt)}</dd>
                  </div>
                  <div>
                    <dt className="text-[var(--color-text-secondary)]">Feedback</dt>
                    <dd>{formatDateTime(event.ruleConfig.feedbackOpenAt)} – {formatDateTime(event.ruleConfig.feedbackCloseAt)}</dd>
                  </div>
                  <div>
                    <dt className="text-[var(--color-text-secondary)]">Capacity</dt>
                    <dd>
                      {event.ruleConfig.capacity} seats
                      {event.ruleConfig.waitlistEnabled ? " · waitlist enabled" : ""}
                    </dd>
                  </div>
                </dl>
              </div>
            </section>

            <aside className="space-y-4">
              <section className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6">
                <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
                  Your registration
                </h2>
                {registrationQuery.isLoading ? (
                  <Skeleton className="mt-4 h-8 w-32" />
                ) : registrationQuery.isError ? (
                  <div className="mt-4">
                    <EmptyFailureBlock
                      variant="failure"
                      title="Could not load registration status"
                      description={registrationQuery.error.message}
                      actionLabel="Retry"
                      onAction={() => void registrationQuery.refetch()}
                    />
                  </div>
                ) : registration ? (
                  <div className="mt-4 space-y-3">
                    <RegistrationStateBadge state={registration.state} />
                    {registrationLabel?.hint ? (
                      <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                        {registrationLabel.hint}
                      </p>
                    ) : null}
                    {registration.waitlistPosition ? (
                      <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                        Queue position: {registration.waitlistPosition}
                      </p>
                    ) : null}
                    {registration.reasonText ? (
                      <Alert variant="warning" title="Status note">
                        {registration.reasonText}
                      </Alert>
                    ) : null}
                    <p className="text-[length:var(--font-size-xs)] text-[var(--color-text-secondary)]">
                      Last updated {formatDateTime(registration.updatedAt)}
                    </p>
                  </div>
                ) : (
                  <p className="mt-4 text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                    You have not registered for this event yet.
                  </p>
                )}
              </section>
            </aside>
          </div>
        </>
      ) : null}
    </div>
  );
}
