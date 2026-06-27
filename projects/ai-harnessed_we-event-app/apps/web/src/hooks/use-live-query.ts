"use client";

import {
  useQuery,
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";

import { getLiveQueryPolicy, type LiveRefreshMode } from "@/lib/query-config";

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
  const policy = getLiveQueryPolicy(mode);

  return useQuery({
    queryKey,
    queryFn,
    enabled,
    ...policy,
    ...options,
  });
}
