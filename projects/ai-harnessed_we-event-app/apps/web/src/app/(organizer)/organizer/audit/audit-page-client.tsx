"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { ServerPaginatedTable } from "@/components/organizer/server-paginated-table";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { useLiveQuery } from "@/hooks/use-live-query";
import { formatDateTime } from "@/lib/format";
import { fetchAuditLogs } from "@/lib/organizer-api";
import { fetchScopedOrganizerEvents } from "@/lib/organizer-events-list";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

const EVENT_PAGE_SIZE = 12;
const AUDIT_PAGE_SIZE = 20;

export default function OrganizerAuditPageClient() {
  const { token, session, isAdmin } = useOrganizerAuth();
  const searchParams = useSearchParams();
  const [eventId, setEventId] = useState(searchParams.get("eventId") ?? "");
  const [eventsPage, setEventsPage] = useState(1);
  const [auditPage, setAuditPage] = useState(1);

  useEffect(() => {
    const fromQuery = searchParams.get("eventId");
    if (fromQuery) {
      setEventId(fromQuery);
    }
  }, [searchParams]);

  useEffect(() => {
    setAuditPage(1);
  }, [eventId]);

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

  const auditListParams = useMemo(
    () => ({ page: auditPage, pageSize: AUDIT_PAGE_SIZE }),
    [auditPage],
  );

  const auditQuery = useLiveQuery({
    queryKey: queryKeys.organizer.audit(eventId, auditListParams),
    queryFn: () => fetchAuditLogs(token!, eventId, auditListParams),
    mode: "organizerDashboard",
    enabled: Boolean(token) && isAdmin && Boolean(eventId),
  });

  if (!isAdmin) {
    return (
      <PageHeader
        title="Audit log"
        subtitle="Only organizer admins can view audit history."
      />
    );
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Audit log"
        subtitle="Critical config and state changes with actor, timestamp, and reason."
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
                <Button
                  size="sm"
                  variant={eventId === event.eventId ? "primary" : "secondary"}
                  onClick={() => setEventId(event.eventId)}
                >
                  {eventId === event.eventId ? "Selected" : "View audit"}
                </Button>
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
          emptyDescription="Create an event to view its audit history."
        />
      </section>

      {!eventId ? (
        <EmptyFailureBlock
          variant="empty"
          title="Select an event"
          description="Choose an event above to view its audit history."
        />
      ) : (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
              Audit entries
            </h2>
            <Button asChild size="sm" variant="ghost">
              <Link href={`/organizer/events/${eventId}`}>Open event dashboard</Link>
            </Button>
          </div>
          <ServerPaginatedTable
            columns={[
              {
                id: "occurred",
                header: "When",
                cell: (row) => formatDateTime(row.occurredAt),
              },
              {
                id: "action",
                header: "Action",
                cell: (row) => row.action,
              },
              {
                id: "entity",
                header: "Entity",
                cell: (row) => `${row.entityType} · ${row.entityId}`,
              },
              {
                id: "actor",
                header: "Actor",
                cell: (row) => `${row.actorId} (${row.actorRole})`,
              },
              {
                id: "reason",
                header: "Reason",
                cell: (row) => row.reasonText ?? row.reasonCode ?? "—",
              },
            ]}
            items={auditQuery.data?.items ?? []}
            rowKey={(row) => row.id}
            page={auditPage}
            pageSize={auditQuery.data?.pageSize ?? AUDIT_PAGE_SIZE}
            total={auditQuery.data?.total ?? 0}
            totalPages={auditQuery.data?.totalPages ?? 1}
            onPageChange={setAuditPage}
            isLoading={auditQuery.isLoading}
            isError={auditQuery.isError}
            errorMessage={auditQuery.error?.message}
            emptyTitle="No audit entries"
            emptyDescription="Lifecycle and configuration changes will appear here."
          />
        </section>
      )}
    </div>
  );
}
