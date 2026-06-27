"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { EventState } from "@we-event/domain";

import { EventStateBadge } from "@/components/participant/event-state-badge";
import { FilterBar } from "@/components/layout/filter-bar";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { ServerPaginatedTable } from "@/components/organizer/server-paginated-table";
import { Button } from "@/components/ui/button";
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
import { fetchScopedOrganizerEvents } from "@/lib/organizer-events-list";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

const EVENT_PAGE_SIZE = 20;

const EVENT_STATE_FILTERS: Array<{ value: "all" | EventState; label: string }> = [
  { value: "all", label: "All states" },
  { value: "Draft", label: "Draft" },
  { value: "Published", label: "Published" },
  { value: "RegistrationOpen", label: "Registration open" },
  { value: "RegistrationClosed", label: "Registration closed" },
  { value: "InProgress", label: "In progress" },
  { value: "Completed", label: "Completed" },
  { value: "Cancelled", label: "Cancelled" },
];

const EVENT_SORT_OPTIONS = [
  { value: "startAt:asc", label: "Start date (soonest)" },
  { value: "updatedAt:desc", label: "Recently updated" },
] as const;

type EventSort = (typeof EVENT_SORT_OPTIONS)[number]["value"];

export default function OrganizerEventsPage() {
  const { token, session, isAdmin } = useOrganizerAuth();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<"all" | EventState>("all");
  const [sort, setSort] = useState<EventSort>("startAt:asc");
  const [page, setPage] = useState(1);

  useEffect(() => {
    const handle = window.setTimeout(() => setSearch(searchInput), 300);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
  }, [search, stateFilter, sort]);

  const listParams = useMemo(
    () => ({
      page,
      pageSize: EVENT_PAGE_SIZE,
      q: search.trim() || undefined,
      state: stateFilter === "all" ? undefined : stateFilter,
      sort,
    }),
    [page, search, stateFilter, sort],
  );

  const eventsQuery = useLiveQuery({
    queryKey: queryKeys.organizer.events.list(listParams),
    queryFn: () => fetchScopedOrganizerEvents(token!, session!, listParams),
    mode: "eventList",
    enabled: Boolean(token && session),
  });

  const items = eventsQuery.data?.items ?? [];
  const total = eventsQuery.data?.total ?? 0;
  const totalPages = eventsQuery.data?.totalPages ?? 1;
  const pageSize = eventsQuery.data?.pageSize ?? EVENT_PAGE_SIZE;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Events"
        subtitle="Manage event lifecycle, capacity, and operational settings."
        actions={
          isAdmin ? (
            <Button asChild>
              <Link href="/organizer/events/new">Create event</Link>
            </Button>
          ) : null
        }
      />

      <FilterBar>
        <Field id="organizer-event-search" label="Search" className="min-w-[12rem] flex-1">
          <Input
            id="organizer-event-search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search by name or location"
          />
        </Field>
        <Field id="organizer-event-state" label="State" className="min-w-[12rem]">
          <Select
            value={stateFilter}
            onValueChange={(value) => setStateFilter(value as "all" | EventState)}
          >
            <SelectTrigger id="organizer-event-state">
              <SelectValue placeholder="All states" />
            </SelectTrigger>
            <SelectContent>
              {EVENT_STATE_FILTERS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field id="organizer-event-sort" label="Sort" className="min-w-[12rem]">
          <Select value={sort} onValueChange={(value) => setSort(value as EventSort)}>
            <SelectTrigger id="organizer-event-sort">
              <SelectValue placeholder="Start date (soonest)" />
            </SelectTrigger>
            <SelectContent>
              {EVENT_SORT_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </FilterBar>

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
              <Link
                href={`/organizer/events/${event.eventId}`}
                className="font-[var(--font-weight-medium)] text-[var(--color-text-primary)] hover:underline"
              >
                {event.name}
              </Link>
            ),
          },
          {
            id: "state",
            header: "State",
            cell: (event) => <EventStateBadge state={event.state} />,
          },
          {
            id: "startAt",
            header: "Starts",
            cell: (event) => formatDateTime(event.startAt),
          },
          {
            id: "location",
            header: "Location",
            cell: (event) => event.location || "—",
          },
          {
            id: "actions",
            header: "",
            cell: (event) => (
              <Button asChild size="sm" variant="ghost">
                <Link href={`/organizer/events/${event.eventId}`}>Open</Link>
              </Button>
            ),
          },
        ]}
        items={items}
        rowKey={(event) => event.eventId}
        page={page}
        pageSize={pageSize}
        total={total}
        totalPages={totalPages}
        onPageChange={setPage}
        isLoading={eventsQuery.isLoading}
        isError={false}
        emptyTitle="No events found"
        emptyDescription={
          session?.role === "OrganizerStaff"
            ? "No assigned events match your filters."
            : "Create an event or adjust your filters."
        }
      />
    </div>
  );
}
