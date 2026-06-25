"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { ServerPaginatedTable } from "@/components/organizer/server-paginated-table";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Field } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useLiveQuery } from "@/hooks/use-live-query";
import { formatDateTime } from "@/lib/format";
import { fetchAuditLogs, fetchOrganizerEvents } from "@/lib/organizer-api";
import { filterEventsForScope } from "@/lib/organizer-rules";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

const PAGE_SIZE = 20;

export default function OrganizerAuditPage() {
  const { token, session, isAdmin } = useOrganizerAuth();
  const searchParams = useSearchParams();
  const [eventId, setEventId] = useState(searchParams.get("eventId") ?? "");
  const [page, setPage] = useState(1);

  useEffect(() => {
    const fromQuery = searchParams.get("eventId");
    if (fromQuery) {
      setEventId(fromQuery);
    }
  }, [searchParams]);

  useEffect(() => {
    setPage(1);
  }, [eventId]);

  const eventsQuery = useLiveQuery({
    queryKey: queryKeys.organizer.events.list({ page: 1, pageSize: 100 }),
    queryFn: () => fetchOrganizerEvents(token!, { page: 1, pageSize: 100 }),
    mode: "eventList",
    enabled: Boolean(token) && isAdmin,
  });

  const events = useMemo(() => {
    const items = eventsQuery.data?.items ?? [];
    if (!session) {
      return items;
    }
    return filterEventsForScope(session, items);
  }, [eventsQuery.data?.items, session]);

  useEffect(() => {
    if (!eventId && events.length > 0) {
      setEventId(events[0]!.eventId);
    }
  }, [eventId, events]);

  const listParams = useMemo(() => ({ page, pageSize: PAGE_SIZE }), [page]);

  const auditQuery = useLiveQuery({
    queryKey: queryKeys.organizer.audit(eventId, listParams),
    queryFn: () => fetchAuditLogs(token!, eventId, listParams),
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

      <Field id="audit-event" label="Event" className="max-w-md">
        <Select value={eventId} onValueChange={setEventId}>
          <SelectTrigger id="audit-event">
            <SelectValue placeholder="Select event" />
          </SelectTrigger>
          <SelectContent>
            {events.map((event) => (
              <SelectItem key={event.eventId} value={event.eventId}>
                {event.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      {eventsQuery.isError ? (
        <EmptyFailureBlock
          variant="failure"
          title="Could not load events"
          description={eventsQuery.error.message}
        />
      ) : null}

      {!eventId ? (
        <EmptyFailureBlock
          variant="empty"
          title="Select an event"
          description="Choose an event to view its audit history."
        />
      ) : (
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
          page={page}
          pageSize={auditQuery.data?.pageSize ?? PAGE_SIZE}
          total={auditQuery.data?.total ?? 0}
          totalPages={auditQuery.data?.totalPages ?? 1}
          onPageChange={setPage}
          isLoading={auditQuery.isLoading}
          isError={auditQuery.isError}
          errorMessage={auditQuery.error?.message}
          emptyTitle="No audit entries"
          emptyDescription="Lifecycle and configuration changes will appear here."
        />
      )}
    </div>
  );
}
