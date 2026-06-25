"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";

import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { ServerPaginatedTable } from "@/components/organizer/server-paginated-table";
import { PageHeader } from "@/components/layout/page-header";
import { useLiveQuery } from "@/hooks/use-live-query";
import { formatDateTime } from "@/lib/format";
import { fetchWaitlist } from "@/lib/organizer-api";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

const PAGE_SIZE = 20;

export default function EventWaitlistPage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;
  const { token } = useOrganizerAuth();
  const [page, setPage] = useState(1);

  const listParams = useMemo(() => ({ page, pageSize: PAGE_SIZE }), [page]);

  const query = useLiveQuery({
    queryKey: queryKeys.organizer.waitlist(eventId, listParams),
    queryFn: () => fetchWaitlist(token!, eventId, listParams),
    mode: "organizerDashboard",
    enabled: Boolean(token),
  });

  const items = query.data?.items ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Waitlist"
        subtitle="FIFO queue order is preserved across pages. Promoted entries show updated status."
      />

      <ServerPaginatedTable
        columns={[
          {
            id: "position",
            header: "Position",
            cell: (row) => row.position,
          },
          {
            id: "participant",
            header: "Participant",
            cell: (row) => row.participantId,
          },
          {
            id: "state",
            header: "Status",
            cell: (row) => <RegistrationStateBadge state={row.state} />,
          },
          {
            id: "enqueued",
            header: "Enqueued",
            cell: (row) => formatDateTime(row.enqueuedAt),
          },
        ]}
        items={items}
        rowKey={(row) => row.waitlistEntryId}
        page={page}
        pageSize={query.data?.pageSize ?? PAGE_SIZE}
        total={query.data?.total ?? 0}
        totalPages={query.data?.totalPages ?? 1}
        onPageChange={setPage}
        isLoading={query.isLoading}
        isError={query.isError}
        errorMessage={query.error?.message}
        emptyTitle="Waitlist is empty"
        emptyDescription="Participants join the waitlist when capacity is full."
      />
    </div>
  );
}
