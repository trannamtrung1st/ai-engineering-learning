"use client";

import Link from "next/link";
import { useMemo } from "react";

import { EventStateBadge } from "@/components/participant/event-state-badge";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLiveQuery } from "@/hooks/use-live-query";
import { formatDateTime } from "@/lib/format";
import { fetchOrganizerEvents } from "@/lib/organizer-api";
import { filterEventsForScope } from "@/lib/organizer-rules";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

export default function OrganizerCheckInHubPage() {
  const { token, session } = useOrganizerAuth();

  const eventsQuery = useLiveQuery({
    queryKey: queryKeys.organizer.events.list({ page: 1, pageSize: 100 }),
    queryFn: () => fetchOrganizerEvents(token!, { page: 1, pageSize: 100 }),
    mode: "eventList",
    enabled: Boolean(token),
  });

  const events = useMemo(() => {
    const items = eventsQuery.data?.items ?? [];
    if (!session) {
      return items;
    }
    return filterEventsForScope(session, items);
  }, [eventsQuery.data?.items, session]);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Check-in"
        subtitle="Open the check-in console for an assigned event."
      />

      {eventsQuery.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-20 w-full" />
          ))}
        </div>
      ) : null}

      {eventsQuery.isError ? (
        <EmptyFailureBlock
          variant="failure"
          title="Could not load events"
          description={eventsQuery.error.message}
          actionLabel="Retry"
          onAction={() => void eventsQuery.refetch()}
        />
      ) : null}

      {eventsQuery.isSuccess && events.length === 0 ? (
        <EmptyFailureBlock
          variant="empty"
          title="No events available"
          description="Assign events to staff or create events as an admin."
        />
      ) : null}

      {events.length > 0 ? (
        <ul className="space-y-3">
          {events.map((event) => (
            <li
              key={event.eventId}
              className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4"
            >
              <div className="space-y-1">
                <p className="font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]">
                  {event.name}
                </p>
                <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                  {formatDateTime(event.startAt)} · {event.location || "—"}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <EventStateBadge state={event.state} />
                <Button asChild size="sm">
                  <Link href={`/organizer/events/${event.eventId}/check-in`}>
                    Open console
                  </Link>
                </Button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
