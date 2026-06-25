"use client";

import { useMemo, useState } from "react";
import type { EventState } from "@we-event/domain";
import { useQueries } from "@tanstack/react-query";

import { EventCard, EventCardSkeleton } from "@/components/participant/event-card";
import { FilterBar } from "@/components/layout/filter-bar";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
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
import { queryKeys } from "@/lib/query-keys";
import { fetchEvents, fetchRegistrationStatus } from "@/lib/participant-api";
import { useAuth } from "@/providers/auth-provider";

const EVENT_STATE_FILTERS: Array<{ value: "all" | EventState; label: string }> = [
  { value: "all", label: "All states" },
  { value: "RegistrationOpen", label: "Registration open" },
  { value: "RegistrationClosed", label: "Registration closed" },
  { value: "InProgress", label: "In progress" },
  { value: "Completed", label: "Completed" },
];

export default function BrowseEventsPage() {
  const { token } = useAuth();
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<"all" | EventState>("all");

  const eventsQuery = useLiveQuery({
    queryKey: queryKeys.events.list(),
    queryFn: () => fetchEvents(token!),
    mode: "eventList",
    enabled: Boolean(token),
  });

  const events = useMemo(
    () => eventsQuery.data?.events ?? [],
    [eventsQuery.data?.events],
  );

  const registrationQueries = useQueries({
    queries: events.map((event) => ({
      queryKey: queryKeys.registrations.status(event.eventId),
      queryFn: () => fetchRegistrationStatus(token!, event.eventId),
      enabled: Boolean(token) && events.length > 0,
      staleTime: 30_000,
    })),
  });

  const registrationByEventId = useMemo(() => {
    const map = new Map<string, (typeof registrationQueries)[number]>();
    events.forEach((event, index) => {
      map.set(event.eventId, registrationQueries[index]!);
    });
    return map;
  }, [events, registrationQueries]);

  const filteredEvents = useMemo(() => {
    const query = search.trim().toLowerCase();
    return events.filter((event) => {
      const matchesSearch =
        !query ||
        event.name.toLowerCase().includes(query) ||
        event.location.toLowerCase().includes(query) ||
        event.description.toLowerCase().includes(query);
      const matchesState = stateFilter === "all" || event.state === stateFilter;
      return matchesSearch && matchesState;
    });
  }, [events, search, stateFilter]);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Browse events"
        subtitle="Discover published events, check availability, and see your registration status."
      />

      <FilterBar>
        <Field id="event-search" label="Search" className="min-w-[12rem] flex-1">
          <Input
            id="event-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
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

      {eventsQuery.isSuccess && filteredEvents.length === 0 ? (
        <EmptyFailureBlock
          variant="empty"
          title="No events match your filters"
          description="Try clearing search or choosing a different event state."
          actionLabel="Clear filters"
          onAction={() => {
            setSearch("");
            setStateFilter("all");
          }}
        />
      ) : null}

      {eventsQuery.isSuccess && filteredEvents.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {filteredEvents.map((event) => {
            const registrationQuery = registrationByEventId.get(event.eventId);
            return (
              <EventCard
                key={event.eventId}
                event={event}
                registration={registrationQuery?.data?.registration}
                registrationLoading={registrationQuery?.isLoading}
                registrationError={
                  registrationQuery?.isError ? registrationQuery.error.message : null
                }
              />
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
