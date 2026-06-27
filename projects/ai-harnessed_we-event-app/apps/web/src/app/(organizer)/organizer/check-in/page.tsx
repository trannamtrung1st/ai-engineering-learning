"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { EventStateBadge } from "@/components/participant/event-state-badge";
import { ServerPaginatedTable } from "@/components/organizer/server-paginated-table";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { useLiveQuery } from "@/hooks/use-live-query";
import { formatDateTime } from "@/lib/format";
import { fetchScopedOrganizerEvents } from "@/lib/organizer-events-list";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

const PAGE_SIZE = 12;

export default function OrganizerCheckInHubPage() {
  const { token, session } = useOrganizerAuth();
  const [page, setPage] = useState(1);

  const listParams = useMemo(
    () => ({ page, pageSize: PAGE_SIZE }),
    [page],
  );

  const eventsQuery = useLiveQuery({
    queryKey: queryKeys.organizer.events.list(listParams),
    queryFn: () => fetchScopedOrganizerEvents(token!, session!, listParams),
    mode: "eventList",
    enabled: Boolean(token && session),
  });

  return (
    <div className="space-y-8">
      <PageHeader
        title="Check-in"
        subtitle="Open the check-in console for an assigned event."
      />

      {eventsQuery.isError ? (
        <EmptyFailureBlock
          variant="failure"
          title="Could not load events"
          description={eventsQuery.error.message}
          actionLabel="Retry"
          onAction={() => void eventsQuery.refetch()}
        />
      ) : null}

      <ServerPaginatedTable
        columns={[
          {
            id: "name",
            header: "Event",
            cell: (event) => (
              <div className="space-y-1">
                <p className="font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]">
                  {event.name}
                </p>
                <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                  {formatDateTime(event.startAt)} · {event.location || "—"}
                </p>
              </div>
            ),
          },
          {
            id: "state",
            header: "State",
            cell: (event) => <EventStateBadge state={event.state} />,
          },
          {
            id: "actions",
            header: "",
            cell: (event) => (
              <Button asChild size="sm">
                <Link href={`/organizer/events/${event.eventId}/check-in`}>
                  Open console
                </Link>
              </Button>
            ),
          },
        ]}
        items={eventsQuery.data?.items ?? []}
        rowKey={(event) => event.eventId}
        page={page}
        pageSize={eventsQuery.data?.pageSize ?? PAGE_SIZE}
        total={eventsQuery.data?.total ?? 0}
        totalPages={eventsQuery.data?.totalPages ?? 1}
        onPageChange={setPage}
        isLoading={eventsQuery.isLoading}
        isError={false}
        emptyTitle="No events available"
        emptyDescription="Assign events to staff or create events as an admin."
      />
    </div>
  );
}
