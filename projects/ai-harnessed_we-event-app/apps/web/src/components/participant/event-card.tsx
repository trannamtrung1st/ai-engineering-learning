"use client";

import Link from "next/link";
import { MapPin } from "lucide-react";

import { EventStateBadge } from "@/components/participant/event-state-badge";
import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/format";
import type { EventListItem, RegistrationStatus } from "@/lib/participant-api";

export interface EventCardProps {
  event: EventListItem;
  registration?: RegistrationStatus | null;
  registrationLoading?: boolean;
  registrationError?: string | null;
}

export function EventCard({
  event,
  registration,
  registrationLoading,
  registrationError,
}: EventCardProps) {
  return (
    <article className="flex flex-col gap-4 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]">
            <Link
              href={`/events/${event.eventId}`}
              className="rounded-[var(--radius-sm)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)]"
            >
              {event.name}
            </Link>
          </h2>
          {event.location ? (
            <p className="flex items-center gap-1.5 text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
              <MapPin className="h-3.5 w-3.5 shrink-0" aria-hidden />
              {event.location}
            </p>
          ) : null}
        </div>
        <EventStateBadge state={event.state} />
      </div>

      <dl className="grid gap-2 text-[length:var(--font-size-sm)]">
        <div>
          <dt className="text-[var(--color-text-secondary)]">Starts</dt>
          <dd className="font-[var(--font-weight-medium)] text-[var(--color-text-primary)]">
            {formatDateTime(event.startAt)}
          </dd>
        </div>
      </dl>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--color-border-default)] pt-4">
        <div className="flex items-center gap-2">
          <span className="text-[length:var(--font-size-xs)] text-[var(--color-text-secondary)]">
            Your status
          </span>
          {registrationLoading ? (
            <Skeleton className="h-6 w-24" />
          ) : registrationError ? (
            <span className="text-[length:var(--font-size-sm)] text-[var(--color-status-rejected)]">
              Status unavailable
            </span>
          ) : registration ? (
            <RegistrationStateBadge state={registration.state} />
          ) : (
            <span className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
              Not registered
            </span>
          )}
        </div>
        <Button asChild size="sm" variant="secondary">
          <Link href={`/events/${event.eventId}`}>View details</Link>
        </Button>
      </div>
    </article>
  );
}

export function EventCardSkeleton() {
  return (
    <div className="space-y-4 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6">
      <Skeleton className="h-6 w-2/3" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-10 w-40" />
      <Skeleton className="h-10 w-32" />
    </div>
  );
}
