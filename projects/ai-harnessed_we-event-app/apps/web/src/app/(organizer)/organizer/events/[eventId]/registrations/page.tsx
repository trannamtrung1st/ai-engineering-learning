"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import type { RegistrationState } from "@we-event/domain";

import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { ServerPaginatedTable } from "@/components/organizer/server-paginated-table";
import { FilterBar } from "@/components/layout/filter-bar";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { fetchRegistrations, fetchStatusHistory } from "@/lib/organizer-api";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

const PAGE_SIZE = 20;

const STATE_FILTERS: Array<{ value: "all" | RegistrationState; label: string }> = [
  { value: "all", label: "All states" },
  { value: "Registered", label: "Registered" },
  { value: "Waitlisted", label: "Waitlisted" },
  { value: "CheckedIn", label: "Checked in" },
  { value: "Attended", label: "Attended" },
  { value: "CancelledByUser", label: "Cancelled by user" },
  { value: "CancelledByOrganizer", label: "Cancelled by organizer" },
];

export default function EventRegistrationsPage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;
  const { token } = useOrganizerAuth();
  const [stateFilter, setStateFilter] = useState<"all" | RegistrationState>("all");
  const [page, setPage] = useState(1);
  const [historyRegistrationId, setHistoryRegistrationId] = useState<string | null>(
    null,
  );
  const [historyPage, setHistoryPage] = useState(1);

  useEffect(() => {
    setPage(1);
  }, [stateFilter]);

  useEffect(() => {
    setHistoryPage(1);
  }, [historyRegistrationId]);

  const listParams = useMemo(
    () => ({
      page,
      pageSize: PAGE_SIZE,
      state: stateFilter === "all" ? undefined : stateFilter,
    }),
    [page, stateFilter],
  );

  const query = useLiveQuery({
    queryKey: queryKeys.organizer.registrations(eventId, listParams),
    queryFn: () => fetchRegistrations(token!, eventId, listParams),
    mode: "organizerDashboard",
    enabled: Boolean(token),
  });

  const historyQuery = useLiveQuery({
    queryKey: queryKeys.organizer.statusHistory(eventId, {
      page: historyPage,
      registrationId: historyRegistrationId ?? undefined,
    }),
    queryFn: () =>
      fetchStatusHistory(token!, eventId, {
        page: historyPage,
        pageSize: PAGE_SIZE,
        registrationId: historyRegistrationId ?? undefined,
      }),
    mode: "organizerDashboard",
    enabled: Boolean(token && historyRegistrationId),
  });

  const items = query.data?.items ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        title="Registrations"
        subtitle="Filter by registration state and open status history to trace changes."
      />

      <FilterBar>
        <Field id="registration-state" label="State" className="min-w-[12rem]">
          <Select
            value={stateFilter}
            onValueChange={(value) =>
              setStateFilter(value as "all" | RegistrationState)
            }
          >
            <SelectTrigger id="registration-state">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATE_FILTERS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </FilterBar>

      <ServerPaginatedTable
        columns={[
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
            id: "waitlist",
            header: "Waitlist #",
            cell: (row) => row.waitlistPosition ?? "—",
          },
          {
            id: "updated",
            header: "Updated",
            cell: (row) => formatDateTime(row.updatedAt),
          },
          {
            id: "reason",
            header: "Reason",
            cell: (row) => row.reasonText ?? "—",
          },
          {
            id: "actions",
            header: "",
            cell: (row) => (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setHistoryRegistrationId(row.registrationId)}
              >
                Status history
              </Button>
            ),
          },
        ]}
        items={items}
        rowKey={(row) => row.registrationId}
        page={page}
        pageSize={query.data?.pageSize ?? PAGE_SIZE}
        total={query.data?.total ?? 0}
        totalPages={query.data?.totalPages ?? 1}
        onPageChange={setPage}
        isLoading={query.isLoading}
        isError={query.isError}
        errorMessage={query.error?.message}
        emptyTitle="No registrations"
        emptyDescription="Participants will appear here once they register."
      />

      <Dialog
        open={Boolean(historyRegistrationId)}
        onOpenChange={() => setHistoryRegistrationId(null)}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Registration status history</DialogTitle>
            <DialogDescription>
              Trace registration state changes with actor, timestamp, and reason.
            </DialogDescription>
          </DialogHeader>
          <ServerPaginatedTable
            columns={[
              {
                id: "when",
                header: "When",
                cell: (row) => formatDateTime(row.occurredAt),
              },
              {
                id: "transition",
                header: "Transition",
                cell: (row) =>
                  `${row.beforeState ?? "—"} → ${row.afterState ?? "—"}`,
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
            items={historyQuery.data?.items ?? []}
            rowKey={(row) => row.id}
            page={historyPage}
            pageSize={historyQuery.data?.pageSize ?? PAGE_SIZE}
            total={historyQuery.data?.total ?? 0}
            totalPages={historyQuery.data?.totalPages ?? 1}
            onPageChange={setHistoryPage}
            isLoading={historyQuery.isLoading}
            isError={historyQuery.isError}
            errorMessage={historyQuery.error?.message}
            emptyTitle="No history entries"
            emptyDescription="Status changes will appear here as the registration progresses."
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
