"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { ServerPaginatedTable } from "@/components/organizer/server-paginated-table";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useLiveQuery } from "@/hooks/use-live-query";
import { ApiClientError } from "@/lib/api-client";
import { formatDateTime } from "@/lib/format";
import { downloadEligibilityExport } from "@/lib/organizer-api";
import { fetchScopedOrganizerEvents } from "@/lib/organizer-events-list";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

const EVENT_PAGE_SIZE = 12;

export default function OrganizerExportPageClient() {
  const { token, session, isAdmin } = useOrganizerAuth();
  const { push } = useToast();
  const [eventId, setEventId] = useState("");
  const [eventsPage, setEventsPage] = useState(1);
  const [exporting, setExporting] = useState(false);

  const eventsListParams = useMemo(
    () => ({ page: eventsPage, pageSize: EVENT_PAGE_SIZE }),
    [eventsPage],
  );

  const eventsQuery = useLiveQuery({
    queryKey: queryKeys.organizer.events.list(eventsListParams),
    queryFn: () => fetchScopedOrganizerEvents(token!, session!, eventsListParams),
    mode: "eventList",
    enabled: Boolean(token && session) && isAdmin,
  });

  async function handleExport(targetEventId: string) {
    if (!token) {
      return;
    }

    setExporting(true);
    try {
      const result = await downloadEligibilityExport(token, targetEventId);
      push({
        title: "Export downloaded",
        description: `${result.filename} (${result.rowCount} rows)`,
        variant: "success",
      });
    } catch (error) {
      push({
        title: "Export failed",
        description:
          error instanceof ApiClientError ? error.message : "Try again.",
        variant: "error",
      });
    } finally {
      setExporting(false);
    }
  }

  if (!isAdmin) {
    return (
      <PageHeader
        title="Export center"
        subtitle="Only organizer admins can export operational reporting data."
      />
    );
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Export center"
        subtitle="Download per-event operational eligibility CSV for internal reporting and governance review."
      />

      {eventsQuery.isError ? (
        <EmptyFailureBlock
          variant="failure"
          title="Could not load events"
          description={eventsQuery.error.message}
        />
      ) : null}

      <section className="space-y-3">
        <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
          Select event
        </h2>
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          Choose an event to export certificate eligibility outcomes, registration
          states, and human-readable reasons.
        </p>
        <ServerPaginatedTable
          columns={[
            {
              id: "name",
              header: "Event",
              cell: (event) => event.name,
            },
            {
              id: "startAt",
              header: "Starts",
              cell: (event) => formatDateTime(event.startAt),
            },
            {
              id: "actions",
              header: "",
              cell: (event) => (
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant={eventId === event.eventId ? "primary" : "secondary"}
                    onClick={() => setEventId(event.eventId)}
                  >
                    {eventId === event.eventId ? "Selected" : "Select"}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={exporting}
                    onClick={() => void handleExport(event.eventId)}
                  >
                    Export CSV
                  </Button>
                </div>
              ),
            },
          ]}
          items={eventsQuery.data?.items ?? []}
          rowKey={(event) => event.eventId}
          page={eventsPage}
          pageSize={eventsQuery.data?.pageSize ?? EVENT_PAGE_SIZE}
          total={eventsQuery.data?.total ?? 0}
          totalPages={eventsQuery.data?.totalPages ?? 1}
          onPageChange={setEventsPage}
          isLoading={eventsQuery.isLoading}
          isError={false}
          emptyTitle="No events"
          emptyDescription="Create an event to export operational data."
        />
      </section>

      {eventId ? (
        <section className="space-y-3 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
          <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
            Export operational data
          </h2>
          <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
            Downloads a CSV attachment with participant eligibility outcomes for
            the selected event.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={exporting}
              onClick={() => void handleExport(eventId)}
            >
              {exporting ? "Exporting…" : "Export operational data"}
            </Button>
            <Button asChild size="sm" variant="ghost">
              <Link href={`/organizer/events/${eventId}`}>Open event dashboard</Link>
            </Button>
            <Button asChild size="sm" variant="ghost">
              <Link href={`/organizer/events/${eventId}/eligibility`}>
                View eligibility list
              </Link>
            </Button>
          </div>
        </section>
      ) : (
        <EmptyFailureBlock
          variant="empty"
          title="Select an event"
          description="Choose an event above or use Export CSV on a row to download operational data."
        />
      )}
    </div>
  );
}
