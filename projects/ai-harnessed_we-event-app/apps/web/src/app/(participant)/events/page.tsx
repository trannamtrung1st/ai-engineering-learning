"use client";

import { useEffect, useMemo, useState } from "react";
import type { EventState } from "@we-event/domain";

import { EventCard, EventCardSkeleton } from "@/components/participant/event-card";
import { FilterBar } from "@/components/layout/filter-bar";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Pagination } from "@/components/ui/pagination";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useLiveQuery } from "@/hooks/use-live-query";
import { useEventRegistrationStatuses } from "@/hooks/use-event-registration-statuses";
import { queryKeys } from "@/lib/query-keys";
import { fetchEvents } from "@/lib/participant-api";
import { useAuth } from "@/providers/auth-provider";

const EVENT_PAGE_SIZE = 12;

const EVENT_STATE_FILTERS: Array<{ value: "all" | EventState; label: string }> = [
  { value: "all", label: "All states" },
  { value: "RegistrationOpen", label: "Registration open" },
  { value: "RegistrationClosed", label: "Registration closed" },
  { value: "InProgress", label: "In progress" },
  { value: "Completed", label: "Completed" },
];

const EVENT_SORT_OPTIONS = [
  { value: "startAt:asc", label: "Start date (soonest)" },
  { value: "updatedAt:desc", label: "Recently updated" },
] as const;

type EventSort = (typeof EVENT_SORT_OPTIONS)[number]["value"];

export default function BrowseEventsPage() {
  const { token } = useAuth();
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
    queryKey: queryKeys.events.list(listParams),
    queryFn: () => fetchEvents(token!, listParams),
    mode: "eventList",
    enabled: Boolean(token),
  });

  const eventIds = useMemo(
    () => (eventsQuery.data?.items ?? []).map((event) => event.eventId),
    [eventsQuery.data?.items],
  );

  const registrationStatuses = useEventRegistrationStatuses(token, eventIds);

  const events = useMemo(
    () => eventsQuery.data?.items ?? [],
    [eventsQuery.data?.items],
  );
  const total = eventsQuery.data?.total ?? 0;
  const totalPages = eventsQuery.data?.totalPages ?? 1;
  const pageSize = eventsQuery.data?.pageSize ?? EVENT_PAGE_SIZE;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Browse events"
        subtitle="Discover published events and review schedules, locations, and your registration status."
      />

      <FilterBar>
        <Field id="event-search" label="Search" className="min-w-[12rem] flex-1">
          <Input
            id="event-search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search by name, location, or description"
          />
        </Field>
        <Field id="event-state-filter" label="Event state" className="min-w-[12rem]">
          <Select
            value={stateFilter}
            onValueChange={(value) => setStateFilter(value as "all" | EventState)}
          >
            <SelectTrigger id="event-state-filter" aria-label="Filter by event state">
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
        <Field id="event-sort" label="Sort by" className="min-w-[12rem]">
          <Select value={sort} onValueChange={(value) => setSort(value as EventSort)}>
            <SelectTrigger id="event-sort" aria-label="Sort by">
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

      {eventsQuery.isLoading ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <EventCardSkeleton key={index} />
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
          title="No results match your filters"
          description="Try clearing search or choosing a different event state."
          actionLabel="Clear filters"
          onAction={() => {
            setSearchInput("");
            setSearch("");
            setStateFilter("all");
            setSort("startAt:asc");
            setPage(1);
          }}
        />
      ) : null}

      {eventsQuery.isSuccess && events.length > 0 ? (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            {events.map((event) => (
              <EventCard
                key={event.eventId}
                event={event}
                registrationState={
                  registrationStatuses.stateByEventId.get(event.eventId) ?? null
                }
                registrationLoading={registrationStatuses.isLoading}
                registrationError={
                  registrationStatuses.hasError
                    ? registrationStatuses.errorMessage
                    : null
                }
              />
            ))}
          </div>

          <Pagination
            page={page}
            pageCount={Math.max(totalPages, 1)}
            total={total}
            pageSize={pageSize}
            onPageChange={setPage}
          />
        </>
      ) : null}
    </div>
  );
}
