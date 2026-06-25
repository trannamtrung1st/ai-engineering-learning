"use client";

import {
  useQuery,
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  LIVE_REFRESH_INTERVALS,
  type LiveRefreshMode,
} from "@/lib/query-config";

type LiveQueryOptions<TData> = Omit<
  UseQueryOptions<TData, Error, TData, QueryKey>,
  "queryKey" | "queryFn"
>;

export interface UseLiveQueryParams<TData> {
  queryKey: QueryKey;
  queryFn: () => Promise<TData>;
  mode: LiveRefreshMode;
  enabled?: boolean;
  options?: LiveQueryOptions<TData>;
}

/**
 * TanStack Query wrapper that applies NFR-06 near-real-time polling policies.
 */
export function useLiveQuery<TData>({
  queryKey,
  queryFn,
  mode,
  enabled = true,
  options,
}: UseLiveQueryParams<TData>): UseQueryResult<TData, Error> {
  const interval = LIVE_REFRESH_INTERVALS[mode];

  return useQuery({
    queryKey,
    queryFn,
    enabled,
    refetchInterval: interval,
    refetchIntervalInBackground: mode !== "checkInConsole",
    refetchOnWindowFocus: true,
    staleTime: Math.floor(interval / 2),
    ...options,
  });
}
