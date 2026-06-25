"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import type { RegistrationState } from "@we-event/domain";

import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { ServerPaginatedTable } from "@/components/organizer/server-paginated-table";
import { FilterBar } from "@/components/layout/filter-bar";
import { PageHeader } from "@/components/layout/page-header";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useLiveQuery } from "@/hooks/use-live-query";
import { formatDateTime } from "@/lib/format";
import { fetchRegistrations } from "@/lib/organizer-api";
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
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<"all" | RegistrationState>("all");
  const [page, setPage] = useState(1);

  useEffect(() => {
    const handle = window.setTimeout(() => setSearch(searchInput), 300);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
  }, [search, stateFilter]);

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

  const items = useMemo(() => {
    const rows = query.data?.items ?? [];
    if (!search.trim()) {
      return rows;
    }
    const needle = search.trim().toLowerCase();
    return rows.filter(
      (row) =>
        row.participantId.toLowerCase().includes(needle) ||
        row.registrationId.toLowerCase().includes(needle),
    );
  }, [query.data?.items, search]);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Registrations"
        subtitle="Search and review participant registration status for this event."
      />

      <FilterBar>
        <Field id="registration-search" label="Search" className="min-w-[12rem] flex-1">
          <Input
            id="registration-search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Participant or registration ID"
          />
        </Field>
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
    </div>
  );
}
