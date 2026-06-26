"use client";

import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import type { RegistrationState } from "@we-event/domain";

import { getLiveQueryPolicy } from "@/lib/query-config";
import { fetchRegistrationStatus } from "@/lib/participant-api";
import { queryKeys } from "@/lib/query-keys";

export interface EventRegistrationStatusLookup {
  stateByEventId: Map<string, RegistrationState>;
  isLoading: boolean;
  hasError: boolean;
  errorMessage: string | null;
}

/**
 * Fetches registration status per visible event (bounded by page size, not full history).
 */
export function useEventRegistrationStatuses(
  token: string | null,
  eventIds: string[],
): EventRegistrationStatusLookup {
  const policy = getLiveQueryPolicy("eventList");

  const queries = useQueries({
    queries: eventIds.map((eventId) => ({
      queryKey: queryKeys.registrations.status(eventId),
      queryFn: () => fetchRegistrationStatus(token!, eventId),
      enabled: Boolean(token) && eventIds.length > 0,
      ...policy,
    })),
  });

  const stateByEventId = useMemo(() => {
    const map = new Map<string, RegistrationState>();
    for (let index = 0; index < eventIds.length; index += 1) {
      const eventId = eventIds[index];
      const state = queries[index]?.data?.registration?.state;
      if (eventId && state) {
        map.set(eventId, state);
      }
    }
    return map;
  }, [eventIds, queries]);

  const isLoading = queries.some((query) => query.isLoading);
  const failedQuery = queries.find((query) => query.isError);
  const hasError = Boolean(failedQuery);
  const errorMessage =
    failedQuery?.error instanceof Error ? failedQuery.error.message : null;

  return { stateByEventId, isLoading, hasError, errorMessage };
}
